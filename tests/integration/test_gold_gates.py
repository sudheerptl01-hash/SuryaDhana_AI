"""Gold program gates (reports/gold_program/PLAN.md §h: T8 host allowlist, T9 repetition, T12 page registries).

Static, file-reading checks: no build, no browser, no network, no live stack. They FAIL (never skip) when a file
they need is missing — the gold program is being delivered, so a missing registry entry or module is exactly
what a gate must catch (desktop review completeness-05). Since wave 1 landed (26 Oct 2026) every gate is green
against the tree; the fixture-based tests at the end prove the checks themselves and must be green at all times.

Comment-proof (wave 1b): every rule reads CODE — TypeScript with ``//`` and ``/* */`` (incl. JSX ``{/* */}``)
comments blanked, Python through the AST (string constants, imports, calls; docstrings dropped). A comment
can neither trip a wording rule nor satisfy a positive one (``routers/gold.py`` mentioning the cached fetcher in
its docstring is not composition).

* **Registries** — 43 pages and one GOLD entry (``gold`` / ``GOLD`` / "Gold terminal", right after MCXG, no ⌘
  digit) agreed by ui/app/page.tsx (TAB_IDS, COMMAND_PAGES, ``lazyTab('gold'``, the render ``case``),
  ui/components/shell/tabModules.ts, ui/components/desktop/pages.ts, desktop/src-tauri/src/pages.rs (PAGE_COUNT,
  the count asserts, the group) and ui/lib/goAliases.ts (XAU, GC); CMDT's label no longer names the gold desk.
* **T9 repetition** — exactly one ``<GoldPreOpen`` render across ui/ and not on CMDT or BRF; Brief.tsx reads the
  gold line once and renders no gold panel; CommodityTab.tsx has no desk; routers/gold.py composes gold_preopen
  (imports ``_yahoo_bars_cached`` or calls ``gp._yahoo_bars_cached`` / ``gp._gold_preopen`` / ``gp.fair_open``,
  which use it inside — PLAN T9's "imports _yahoo_bars_cached only" forbids a SECOND fetcher, it does not mandate
  the name) and defines no Yahoo fetcher of its own; ui-api's Yahoo URL literals (string constants, not comments)
  stay the existing four (commodity.py, news_scanner.py ×2, gold_preopen.py).
* **T8 host allowlist** — over services/data-service/gold/** and routers/gold.py: every FETCHED host is in PLAN
  §c.6; the forbidden publishers (www.cmegroup.com, mcxindia.com, kitco.com, prices.lbma.org.uk, stooq.com,
  goldprice.org, investing.com) are never fetched; FRED's REST host appears only in a FILE that reads
  FRED_API_KEY. A URL that is only LINKED (PLAN "LINK-ONLY") is exempt when its AST context says so — a
  ``link``/``links``/``href`` keyword or dict key, a ``LINKS``/``*_LINK`` name — or a COMMENT on its line or the
  line above says ``link`` / ``link-only`` (tokenised comments only: the string's own text, ``/links.html``, never
  counts), and catalog_seed.py is link context throughout. PLAN §d's ``*_url`` response keys are deliberately NOT
  link markers: a link-only URL in the router sits behind a ``_LINK`` name or carries ``# link-only``. A host
  inside a container NAMED as a denylist (hosts.py ``FORBIDDEN_HOST_FRAGMENTS``) is what the wrapper refuses, not
  what it fetches, and is exempt too (AST names only, never free text). A bare literal counts as a host only when
  it ends in a public suffix the gold sources use (``ftplib.FTP("ftp.cmegroup.com")``): log event names
  (``gold.http.get``), cache and logger names (``gold.store``, ``ui-api.gold``) and Yahoo symbols (``GCZ26.CMX``)
  are not hosts. Docstrings are ignored. T8 is a static guard: hosts.py ``assert_allowed`` on every request path
  is the enforcing layer.
"""
from __future__ import annotations

import ast
import io
import os
import re
import sys
import tokenize
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from desktop_qa.pages import PAGE_TSX, PAGES_RS, PageSource, load_page_source, parse_rust_pages

PAGE_COUNT = 43
GOLD_ID, GOLD_CODE, GOLD_LABEL = "gold", "GOLD", "Gold terminal"
GOLD_AFTER = "mcxgold"                 # GOLD sits right after MCXG (next to CMDT/MCXG, PLAN §a.1)
GOLD_ALIASES = ("XAU", "GC")           # PM decision; PLAN §a.1's GPHY/GMAC/LRN/COT are B4A's call
GOLD_COMPONENT_DIR = "@/components/gold/"   # PLAN B4: the page and its sub-views live in ui/components/gold/

UI = ROOT / "ui"
TAB_MODULES_TS = UI / "components" / "shell" / "tabModules.ts"
DESKTOP_PAGES_TS = UI / "components" / "desktop" / "pages.ts"
GO_ALIASES_TS = UI / "lib" / "goAliases.ts"
BRIEF_TSX = UI / "components" / "Brief.tsx"
COMMODITY_TSX = UI / "components" / "CommodityTab.tsx"
UI_API = ROOT / "services" / "ui-api"
GOLD_ROUTER = UI_API / "routers" / "gold.py"
DATA_GOLD_PKG = ROOT / "services" / "data-service" / "gold"

UI_SKIP_DIRS = frozenset({"node_modules", "dist", "out", "__tests__"})   # builds, deps, checks: never a render source

# ── T8 vocabulary (PLAN §c.6, §h T8) ───────────────────────────────────────────────────────────────
ALLOWED_HOSTS = frozenset({
    "query1.finance.yahoo.com", "query2.finance.yahoo.com", "publicreporting.cftc.gov", "www.cftc.gov",
    "ftp.cmegroup.com", "home.treasury.gov", "fred.stlouisfed.org", "api.spdrgoldshares.com", "www.ishares.com",
    "fsapi.gold.org", "api.imf.org", "cdn.lbma.org.uk", "www.lbma.org.uk", "en.sge.com.cn", "www.sge.com.cn",
    "www.shfe.com.cn", "ibjarates.com", "www.rbi.org.in", "directlink.icicidirect.com", "zerodha.com",
    "portal.amfiindia.com", "pib.gov.in", "ocean.nivel.bazg.admin.ch", "www.atlantafed.org", "nfs.faireconomy.media",
    "www.bea.gov", "www.matteoiacoviello.com", "thedocs.worldbank.org", "api.gold-api.com", "news.google.com",
})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})   # ui-api ↔ data-service defaults, never a publisher
FORBIDDEN_HOSTS = ("www.cmegroup.com", "mcxindia.com", "kitco.com", "prices.lbma.org.uk", "stooq.com",
                   "goldprice.org", "investing.com")
FRED_REST_HOST = "api.stlouisfed.org"
FRED_KEY_NAME = "FRED_API_KEY"
# AST names: "link"/"links"/"href" as a whole word or a snake_case part (LINKS, reuters_link, FEDWATCH_LINK, href=)
LINK_NAME = re.compile(r"(?<![a-z])(?:links?|href)(?![a-z])", re.IGNORECASE)
# comments (tokenised, never the string's own text): "# link-only", "# link: …", "# shown as a link" on the line or above
LINK_COMMENT = re.compile(r"(?<![a-z])links?(?![a-z])|link[-_ ]only", re.IGNORECASE)
LINK_FILES = re.compile(r"catalog_seed", re.IGNORECASE)
# a container NAMED as a denylist holds the hosts the client wrapper refuses (hosts.py FORBIDDEN_HOST_FRAGMENTS), not
# hosts it fetches; matched against AST names only (assignment target, keyword / dict key, called function)
DENY_CONTEXT = re.compile(r"forbid|deny|never", re.IGNORECASE)
URL_HOST = re.compile(r"(?:https?|ftp)://([A-Za-z0-9.\-]+)")
# a bare literal is a host only when it looks like one AND ends in a public suffix the gold sources use (PLAN §c.6):
# ftplib.FTP("ftp.cmegroup.com") yes; "gold.http.get", "gold.store", "ui-api.gold", "GCZ26.CMX" no
BARE_HOST = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+$", re.IGNORECASE)
HOST_SUFFIXES = frozenset({"com", "org", "net", "gov", "edu", "int", "info", "io", "in", "cn", "uk", "ch", "media"})

# ── T9 vocabulary ──────────────────────────────────────────────────────────────────────────────────
YAHOO_LITERAL = "finance.yahoo.com"
YAHOO_LITERAL_FILES_TODAY = {"commodity.py": 1, "news_scanner.py": 2, "gold_preopen.py": 1}   # the existing four
GOLD_PREOPEN_RENDER = re.compile(r"<GoldPreOpen(?=\s|/>)")   # a JSX render; not get<GoldPreOpen> / Omit<GoldPreOpen,
GOLD_PANEL = re.compile(r"<Panel\b[^>]*?\btitle=(?:\"[^\"]*gold[^\"]*\"|'[^']*gold[^']*'|\{`[^`]*gold[^`]*`\})",
                        re.IGNORECASE | re.DOTALL)
# the one read of the gold line: a get/use/fetchGold* helper other than the retired desk helpers, or the path itself
GOLD_LINE_CALL = re.compile(r"\b(?:get|use|fetch)Gold(?!PreOpen\b|Log\b|Actual\b)\w*\s*\(|['\"`]/api/gold/health")
# PLAN §b: the desk read and the accuracy-log read leave BRF (the line carries the miss; the log is GOLD › h.accuracy)
RETIRED_BRIEF_CALLS = ("getGoldPreOpen", "getGoldLog")
CACHED_FETCHER = "_yahoo_bars_cached"
UNCACHED_FETCHER = "_yahoo_bars"
GOLD_PREOPEN_MODULE = "gold_preopen"
# gold_preopen entry points that use the cached fetcher inside: composing any of them is "one fetcher for Yahoo"
COMPOSES_CACHED = frozenset({CACHED_FETCHER, "_gold_preopen", "fair_open"})


def need(path: Path, owner: str) -> None:
    """Fail, never skip, when a source the gate needs is absent (names the builder who delivers it)."""
    if not path.exists():
        pytest.fail(f"{path.relative_to(ROOT)} is missing — delivered by {owner} (gold program PLAN §0.2); the gate "
                    f"stays red until it lands", pytrace=False)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# pure helpers (unit-tested on fixtures below, applied to the real tree in the gates)
# ══════════════════════════════════════════════════════════════════════════════════════════════════

def walk_sources(root: Path, suffixes: tuple[str, ...], skip_dirs: frozenset[str] = UI_SKIP_DIRS) -> list[Path]:
    """Source files under ``root`` with one of ``suffixes``, pruning dot-dirs and ``skip_dirs`` (no symlink descent)."""
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in skip_dirs)
        for f in filenames:
            if f.endswith(suffixes) and ".test." not in f and not f.endswith(".check.ts"):
                out.append(Path(dirpath) / f)
    return sorted(out)


def strip_ts_comments(src: str) -> str:
    """TypeScript/TSX with ``//`` and ``/* */`` comments blanked (newlines kept, so line numbers survive).

    A tiny scanner, not a parser: it tracks ``'``, ``"`` and backtick strings (with escapes) so a ``//`` inside a
    URL literal or a ``/*`` inside a string is left alone; template-literal ``${}`` nesting is treated as string
    text, which is right for every comment this gate cares about (a commented-out render or call).
    """
    out: list[str] = []
    i, n = 0, len(src)
    quote: str | None = None
    while i < n:
        c = src[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"', "`"):
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join("\n" if ch == "\n" else " " for ch in src[i:j]))
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def gold_preopen_renders(files: Iterable[Path]) -> list[tuple[Path, int]]:
    """Every JSX render ``<GoldPreOpen`` (not ``<GoldPreOpenX``) as (file, line); comments blanked first."""
    hits: list[tuple[Path, int]] = []
    for p in files:
        code = strip_ts_comments(p.read_text(encoding="utf-8", errors="replace"))
        for i, line in enumerate(code.splitlines(), 1):
            if GOLD_PREOPEN_RENDER.search(line):
                hits.append((p, i))
    return hits


def brief_violations(src: str) -> list[str]:
    """T9 rules for Brief.tsx (comments blanked): no retired desk/log call, no gold panel, one read of the gold line."""
    code = strip_ts_comments(src)
    out = [f"still calls {name}( — PLAN §b: Brief reads /api/gold/health.line instead (the log is GOLD › h.accuracy)"
           for name in RETIRED_BRIEF_CALLS if re.search(rf"\b{name}\s*\(", code)]
    panels = GOLD_PANEL.findall(code)
    if panels:
        out.append(f"renders a gold panel ({len(panels)}): PLAN §b allows one Line in the Market panel, no panel")
    calls = GOLD_LINE_CALL.findall(code)
    if len(calls) != 1:
        out.append(f"reads the gold line {len(calls)} times, expected exactly 1 (a getGoldHealth* helper or "
                   f"'/api/gold/health'): {calls}")
    return out


def commodity_violations(src: str) -> list[str]:
    """T9 rules for CommodityTab.tsx (comments blanked): the desk and its log are gone, no label/subtitle sells a desk."""
    code = strip_ts_comments(src)
    out = []
    for name in ("GoldPreOpen", "GoldAccuracyLog"):
        if re.search(rf"\b{name}\b", code):
            out.append(f"still references {name} (PLAN §b: CMDT drops the desk)")
    if re.search(r"pre-open desk|gold desk", code, re.IGNORECASE):
        out.append("label/hint/subtitle still names the gold desk")
    return out


def _gold_preopen_aliases(tree: ast.AST) -> set[str]:
    """Names the module ``gold_preopen`` is bound to (``from routers import gold_preopen as gp``, ``import … as x``)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {a.asname or a.name for a in node.names if a.name == GOLD_PREOPEN_MODULE}
        elif isinstance(node, ast.Import):
            names |= {a.asname or a.name for a in node.names if a.name.rsplit(".", 1)[-1] == GOLD_PREOPEN_MODULE}
    return names


def gold_router_violations(src: str) -> list[str]:
    """T9 rules for routers/gold.py, on the AST: compose gold_preopen's cached Yahoo fetcher (by importing
    ``_yahoo_bars_cached`` or calling ``<alias>._yahoo_bars_cached`` / ``._gold_preopen`` / ``.fair_open``), carry
    no Yahoo URL / yfinance in code, never call the uncached ``_yahoo_bars``. Comments and docstrings count for
    nothing either way."""
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"does not parse: {exc}"]
    out = []
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").rsplit(".", 1)[-1] == GOLD_PREOPEN_MODULE:
            imported_names |= {a.name for a in node.names}
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            if any(m.split(".")[0] == "yfinance" for m in mods):
                out.append("imports yfinance: a fifth fetcher (T9)")
    aliases = _gold_preopen_aliases(tree)
    calls = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)]
    composed = {f.attr for f in calls if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                and f.value.id in aliases and f.attr in COMPOSES_CACHED}
    if CACHED_FETCHER not in imported_names and not composed:
        out.append(f"does not compose gold_preopen ({CACHED_FETCHER}, or _gold_preopen( / fair_open( through its alias): "
                   f"PLAN 0.1 #2, one fetcher for Yahoo")
    strings = [v for _, v, _ in code_strings(src)]
    if any(YAHOO_LITERAL in v or "/finance/chart/" in v for v in strings):
        out.append("contains a Yahoo URL in code: a fifth fetcher (T9)")
    if any(_name_of(f) == UNCACHED_FETCHER for f in calls) or UNCACHED_FETCHER in imported_names:
        out.append("calls the uncached _yahoo_bars( (SWR/single-flight bypassed)")
    return out


def yahoo_literal_counts(root: Path) -> dict[str, int]:
    """Occurrences of the Yahoo host literal in string CONSTANTS per .py file under ``root`` (tests excluded), by
    basename; comments and docstrings do not count (a file that does not parse counts its raw text)."""
    out: dict[str, int] = {}
    for p in walk_sources(root, (".py",), frozenset({"tests", "__pycache__"})):
        src = p.read_text(encoding="utf-8", errors="replace")
        if YAHOO_LITERAL not in src:
            continue
        try:
            n = sum(v.count(YAHOO_LITERAL) for _, v, _ in code_strings(src))
        except SyntaxError:
            n = src.count(YAHOO_LITERAL)
        if n:
            out[p.name] = out.get(p.name, 0) + n
    return out


@dataclass
class HostScan:
    """Hosts found in non-docstring string literals: fetched, merely linked, or listed as refused (a denylist)."""

    fetched: dict[str, set[str]] = field(default_factory=dict)
    linked: dict[str, set[str]] = field(default_factory=dict)
    denied: dict[str, set[str]] = field(default_factory=dict)                  # inside a container named as a denylist
    forbidden: list[tuple[str, int, str]] = field(default_factory=list)        # fetched forbidden publisher
    not_allowlisted: list[tuple[str, int, str]] = field(default_factory=list)  # fetched host outside §c.6
    fred_rest: list[tuple[str, int]] = field(default_factory=list)             # api.stlouisfed.org fetched
    fred_key_files: set[str] = field(default_factory=set)                      # files that read FRED_API_KEY (code)

    @property
    def reads_fred_key(self) -> bool:
        return bool(self.fred_key_files)

    def fred_rest_without_key(self) -> list[tuple[str, int]]:
        """FRED REST uses in a file that does not itself read the key (the keyless path is fredgraph.csv)."""
        return [(f, n) for f, n in self.fred_rest if f not in self.fred_key_files]


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def _name_of(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _context_names(node: ast.AST, parent: dict[ast.AST, ast.AST]) -> list[str]:
    """What a string literal belongs to, innermost first: the keyword or dict key it is the value of, the function it
    is a positional argument of, and the enclosing assignment's target(s) (where the climb stops)."""
    names: list[str] = []
    child, cur = node, parent.get(node)
    while cur is not None:
        if isinstance(cur, ast.keyword) and cur.arg:
            names.append(cur.arg)
        elif isinstance(cur, ast.Dict) and any(v is child for v in cur.values):
            key = cur.keys[next(i for i, v in enumerate(cur.values) if v is child)]
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                names.append(key.value)
        elif isinstance(cur, ast.Call) and any(a is child for a in cur.args):
            fn = _name_of(cur.func)
            if fn:
                names.append(fn)
        elif isinstance(cur, ast.Assign):
            names += [n for n in (_name_of(t) for t in cur.targets) if n]
            break
        elif isinstance(cur, ast.AnnAssign):
            target = _name_of(cur.target)
            if target:
                names.append(target)
            break
        elif isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            break
        child, cur = cur, parent.get(cur)
    return names


def code_strings(src: str) -> list[tuple[int, str, str]]:
    """(line, value, context) of every string constant that is code, not a docstring (f-string parts included).

    ``context`` is the literal's AST names joined by spaces (see ``_context_names``), e.g. ``"FORBIDDEN_HOST_FRAGMENTS"``,
    ``"href LINKS"`` or ``"FTP"``. Comments are not in the AST; ``comment_lines`` tokenises them for the link rule.
    """
    tree = ast.parse(src)
    docs = _docstring_ids(tree)
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    consts = sorted((node for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
                     and id(node) not in docs), key=lambda n: (n.lineno, n.col_offset))   # source order, not BFS order
    return [(node.lineno, node.value, " ".join(_context_names(node, parent))) for node in consts]


def comment_lines(src: str) -> dict[int, str]:
    """Line → comment text for every ``#`` COMMENT token (never a ``#`` inside a string)."""
    out: dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = out.get(tok.start[0], "") + tok.string
    except (tokenize.TokenError, SyntaxError):
        pass
    return out


def _is_forbidden(host: str) -> bool:
    return any(host == f or host.endswith("." + f) for f in FORBIDDEN_HOSTS)


def bare_host(value: str) -> str | None:
    """``value`` lower-cased when it is a bare host name (shape + public suffix), else None."""
    v = value.strip().lower()
    return v if BARE_HOST.match(v) and v.rsplit(".", 1)[-1] in HOST_SUFFIXES else None


def scan_hosts(files: Iterable[Path], root: Path) -> HostScan:
    """Classify every host literal in ``files`` (T8). ``root`` only shortens the reported paths."""
    scan = HostScan()
    for p in files:
        src = p.read_text(encoding="utf-8")
        rel = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
        strings = code_strings(src)
        if any(FRED_KEY_NAME in v for _, v, _ in strings):      # the key is read in CODE (os.environ[...]/getenv), not a comment
            scan.fred_key_files.add(rel)
        comments = comment_lines(src)
        file_is_links = bool(LINK_FILES.search(p.name))
        for lineno, value, context in strings:
            hosts = [h.lower() for h in URL_HOST.findall(value)]
            if not hosts:
                bare = bare_host(value)
                hosts = [bare] if bare else []
            if not hosts:
                continue
            # the comment rule reads tokenised comments on the literal's line or the one above — never the literal itself
            commented = LINK_COMMENT.search(comments.get(lineno, "")) or LINK_COMMENT.search(comments.get(lineno - 1, ""))
            if DENY_CONTEXT.search(context):
                bucket = scan.denied
            elif file_is_links or LINK_NAME.search(context) or commented:
                bucket = scan.linked
            else:
                bucket = scan.fetched
            for host in hosts:
                bucket.setdefault(rel, set()).add(host)
                if bucket is not scan.fetched:
                    continue
                if _is_forbidden(host):
                    scan.forbidden.append((rel, lineno, host))
                elif host == FRED_REST_HOST:
                    scan.fred_rest.append((rel, lineno))
                elif host not in ALLOWED_HOSTS and host not in LOOPBACK_HOSTS:
                    scan.not_allowlisted.append((rel, lineno, host))
    return scan


#: Terminal v2 (PLAN 1.7 G5, B6-GATES): the three new ui-api routers join the T8 host scan (they must exist). markets.py is
#: NOT in the set: its pre-existing eco-calendar fetchers name www.federalreserve.gov, outside the gold allowlist; its v2
#: drivers section is scanned by services/ui-api/tests/test_terminal_v2_api.py::test_routers_name_no_publisher_host.
TV2_ROUTERS = tuple(GOLD_ROUTER.parent / n for n in ("derivatives.py", "data_health.py", "options_strategy.py"))


def gold_fetch_sources() -> list[Path]:
    """The T8 scan set: services/data-service/gold/**/*.py (B1) and routers/gold.py (B3); both must exist.
    Terminal v2 (PLAN 1.7 G5): also TV2_ROUTERS (routers/derivatives.py, data_health.py, options_strategy.py) — 1 + 3
    routers; see TV2_ROUTERS for why markets.py is not here."""
    need(DATA_GOLD_PKG, "B1 data")
    need(GOLD_ROUTER, "B3 api")
    for r in TV2_ROUTERS:
        need(r, "Terminal v2 B3 api")
    files = walk_sources(DATA_GOLD_PKG, (".py",), frozenset({"tests", "__pycache__"}))
    return files + [GOLD_ROUTER, *TV2_ROUTERS]


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# gates against the real tree (red until B4A / B3 / B1 land; never skipped)
# ══════════════════════════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def ui_pages() -> PageSource:
    need(PAGE_TSX, "the UI (page.tsx)")
    return load_page_source(PAGE_TSX)


class TestPageRegistries:
    """Every registry carries 43 pages and the same GOLD entry (PLAN Appendix A; B4A for the UI, B6 for Rust)."""

    def test_page_tsx_registers_gold_as_the_43rd_page(self, ui_pages: PageSource):
        assert len(ui_pages.tab_ids) == PAGE_COUNT, (f"B4A: TAB_IDS lists {len(ui_pages.tab_ids)} pages, expected "
                                                     f"{PAGE_COUNT} (42 + gold)")
        assert GOLD_ID in ui_pages.tab_ids, "B4A: 'gold' is not in TAB_IDS"
        page = ui_pages.by_id.get(GOLD_ID)
        assert page is not None, "B4A: COMMAND_PAGES has no gold entry"
        assert (page.id, page.code, page.label) == (GOLD_ID, GOLD_CODE, GOLD_LABEL)
        assert page.hint, "B4A: the GOLD entry needs its GO-bar hint (PLAN §a.1)"
        ids = [p.id for p in ui_pages.command_pages]
        assert ids.index(GOLD_ID) == ids.index(GOLD_AFTER) + 1, "B4A: GOLD must follow MCXG in COMMAND_PAGES (pages.rs mirrors it)"
        src = PAGE_TSX.read_text()
        assert re.search(r"lazyTab\(\s*'gold'", src), "B4A: page.tsx has no lazyTab('gold', …)"
        assert re.search(r"case\s+'gold'\s*:", src), "B4A: page.tsx's render switch has no case 'gold'"

    def test_tab_modules_loads_gold_from_components_gold(self, ui_pages: PageSource):
        need(TAB_MODULES_TS, "B4A")
        src = TAB_MODULES_TS.read_text()
        keys = set(re.findall(r"(?m)^\s*([a-z]+)\s*:\s*\(\)\s*=>\s*import\(", src))
        assert GOLD_ID in keys, "B4A: tabModules.ts has no loader for gold"
        assert re.search(rf"(?m)^\s*gold\s*:\s*\(\)\s*=>\s*import\('{re.escape(GOLD_COMPONENT_DIR)}", src), \
            f"B4A: the gold loader must import from {GOLD_COMPONENT_DIR} (PLAN B4)"
        split_pages = set(ui_pages.tab_ids) - {"brief"}   # the brief is not code-split (tabModules.ts preloadTab)
        assert split_pages <= keys, f"pages without a split loader: {sorted(split_pages - keys)}"

    def test_desktop_page_meta_has_gold(self, ui_pages: PageSource):
        need(DESKTOP_PAGES_TS, "B4A")
        src = DESKTOP_PAGES_TS.read_text()
        assert re.search(rf"(?m)^\s*gold\s*:\s*\{{\s*code:\s*'{GOLD_CODE}'\s*,\s*label:\s*'{GOLD_LABEL}'\s*\}}", src), \
            "B4A: ui/components/desktop/pages.ts PAGE_META lacks gold: { code: 'GOLD', label: 'Gold terminal' }"
        ids = re.findall(r"(?m)^\s*([a-z]+)\s*:\s*\{\s*code:", src)
        assert len(ids) == PAGE_COUNT and set(ids) == set(ui_pages.tab_ids)
        assert "42 terminal pages" not in src, "B4A: the header comment still says 42 pages"

    def test_pages_rs_has_43_pages_with_gold_after_mcxg(self, ui_pages: PageSource):
        need(PAGES_RS, "B6 gates")
        src = PAGES_RS.read_text()
        rs = parse_rust_pages(src)
        assert len(rs) == PAGE_COUNT
        assert f"pub const PAGE_COUNT: usize = {PAGE_COUNT};" in src
        assert len(re.findall(rf"assert_eq!\([^;]*?\b{PAGE_COUNT}\b", src)) >= 3, "the three count asserts must say 43"
        assert not re.search(r"assert_eq!\([^;]*?\b42\b", src), "a count assert still says 42"
        gold = next((p for p in rs if p.id == GOLD_ID), None)
        assert gold is not None and (gold.code, gold.label) == (GOLD_CODE, GOLD_LABEL)
        assert re.search(r'id: "gold"[^}]*group: Group::DerivativesGold[^}]*shortcut: 0', src), \
            "GOLD must be in the DerivativesGold group with no Cmd digit"
        assert [(p.id, p.code, p.label) for p in rs] == [(p.id, p.code, p.label) for p in ui_pages.command_pages], \
            "pages.rs and COMMAND_PAGES disagree (ids, codes, labels or order)"

    def test_cmdt_label_no_longer_names_the_gold_desk(self, ui_pages: PageSource):
        need(PAGES_RS, "B6 gates")
        need(DESKTOP_PAGES_TS, "B4A")
        labels = {"page.tsx": ui_pages.by_id["commodity"].label,
                  "pages.rs": next(p.label for p in parse_rust_pages(PAGES_RS.read_text()) if p.id == "commodity")}
        m = re.search(r"(?m)^\s*commodity\s*:\s*\{\s*code:\s*'CMDT'\s*,\s*label:\s*'((?:[^'\\]|\\.)*)'", DESKTOP_PAGES_TS.read_text())
        labels["pages.ts"] = m.group(1) if m else "<missing>"
        bad = {k: v for k, v in labels.items() if "gold" in v.lower()}
        assert not bad, f"PLAN §b: CMDT drops '· Gold desk' from its label; still there in {bad}"
        assert len(set(labels.values())) == 1, f"CMDT label differs between registries: {labels}"

    def test_go_aliases_xau_and_gc_open_gold(self):
        need(GO_ALIASES_TS, "B4A")
        src = GO_ALIASES_TS.read_text()
        for alias in GOLD_ALIASES:
            m = re.search(rf"(?m)^\s*{alias}\s*:\s*\[(.*?)\]", src)
            assert m and re.search(r"kind:\s*'page'\s*,\s*id:\s*'gold'", m.group(1)), \
                f"B4A: GO alias {alias} must open the gold page (PM decision)"


class TestRepetitionT9:
    """PLAN §h T9: the pre-open desk renders on one page; no second Yahoo path; BRF/CMDT keep a line, not a panel."""

    def test_exactly_one_component_renders_gold_pre_open_and_not_cmdt_or_brf(self):
        need(UI / "components", "the UI")
        hits = gold_preopen_renders(walk_sources(UI, (".tsx", ".ts")))
        where = [f"{p.relative_to(ROOT)}:{i}" for p, i in hits]
        assert len(hits) == 1, f"<GoldPreOpen /> must render exactly once across ui/ (found {len(hits)}): {where}"
        assert hits[0][0].name not in ("CommodityTab.tsx", "Brief.tsx"), \
            f"B4A: the desk still renders on {where[0]} — it belongs to ui/components/gold/GoldPage.tsx (PLAN §b)"

    def test_brief_reads_one_gold_line_and_renders_no_gold_panel(self):
        need(BRIEF_TSX, "the UI")
        bad = brief_violations(BRIEF_TSX.read_text())
        assert not bad, "B4A: Brief.tsx — " + "; ".join(bad)

    def test_commodity_tab_has_no_desk(self):
        need(COMMODITY_TSX, "the UI")
        bad = commodity_violations(COMMODITY_TSX.read_text())
        assert not bad, "B4A: CommodityTab.tsx — " + "; ".join(bad)

    def test_gold_router_composes_gold_preopen_and_adds_no_fetcher(self):
        need(GOLD_ROUTER, "B3 api")
        bad = gold_router_violations(GOLD_ROUTER.read_text())
        assert not bad, "B3: routers/gold.py — " + "; ".join(bad)

    def test_ui_api_yahoo_fetchers_remain_the_existing_four(self):
        need(UI_API / "routers", "ui-api")
        found = yahoo_literal_counts(UI_API)
        new_files = sorted(set(found) - set(YAHOO_LITERAL_FILES_TODAY))
        assert not new_files, f"a new ui-api module talks to Yahoo directly (T9: no fifth fetcher): {new_files}"
        assert sum(found.values()) <= sum(YAHOO_LITERAL_FILES_TODAY.values()), \
            f"more Yahoo URL literals than the existing four: {found}"
        assert "gold.py" not in found and "mcx.py" not in found


class TestHostAllowlistT8:
    """PLAN §h T8 over services/data-service/gold/** and routers/gold.py (B1, B3)."""

    @pytest.fixture(scope="class")
    def scan(self) -> HostScan:
        return scan_hosts(gold_fetch_sources(), ROOT)

    def test_every_fetched_host_is_allowlisted(self, scan: HostScan):
        assert not scan.not_allowlisted, ("hosts outside PLAN §c.6 (fetched, or a link not marked as one): "
                                          + "; ".join(f"{f}:{n} {h}" for f, n, h in scan.not_allowlisted))

    def test_forbidden_publishers_are_never_fetched(self, scan: HostScan):
        assert not scan.forbidden, ("forbidden host in fetch context (LINK-ONLY publishers must sit on a line with a "
                                    "link/href key, a LINKS name or '# link-only'): "
                                    + "; ".join(f"{f}:{n} {h}" for f, n, h in scan.forbidden))

    def test_fred_rest_only_in_a_file_that_reads_the_key(self, scan: HostScan):
        bad = scan.fred_rest_without_key()
        assert not bad, (f"{FRED_REST_HOST} used in a file that does not read {FRED_KEY_NAME} (the keyless path is "
                         f"fredgraph.csv on fred.stlouisfed.org): {bad}; key read in {sorted(scan.fred_key_files)}")

    def test_scan_set_is_not_empty(self):
        files = gold_fetch_sources()
        assert any(p.name != "__init__.py" for p in files if p.is_relative_to(DATA_GOLD_PKG)), \
            "B1: services/data-service/gold/ holds no ingest modules yet"
        routers = [p for p in files if p.parent == GOLD_ROUTER.parent]
        assert len(routers) == 4 and GOLD_ROUTER in routers, routers           # gold.py + the three Terminal v2 routers


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# the checks themselves, on fixtures (green at all times; negative controls included)
# ══════════════════════════════════════════════════════════════════════════════════════════════════

class TestGateHelpers:
    def test_scan_hosts_classifies_fetch_link_deny_docstring_and_bare_hosts(self, tmp_path: Path):
        pkg = tmp_path / "gold"
        pkg.mkdir()
        (pkg / "ingest_cot.py").write_text(
            '"""Fetches CFTC; never www.cmegroup.com (a docstring is not code)."""\n'
            'import ftplib\n'
            'BASE = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"\n'
            'CURVE = ("GCZ26.CMX", "GCG27.CMX")                  # Yahoo symbols are not hosts\n'
            'def ftp():\n'
            '    """Talks to www.kitco.com? no: docstring."""\n'
            '    logger.info("gold.ftp.get", host="x")           # a log event name is not a host\n'
            '    return ftplib.FTP("ftp.cmegroup.com")\n'
            'def chart(sym):\n'
            '    return f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"\n'
            'LOCAL = "http://127.0.0.1:8001/db/gold/series"\n'
            'STORE = SWRCache("gold.store"); LOG = logging.getLogger("ui-api.gold")\n')
        (pkg / "ingest_bad.py").write_text(
            'A = "https://www.kitco.com/charts/gold"\n'
            'B = "https://api.stlouisfed.org/fred/series/observations?series_id=DFII10"\n'
            'C = "https://example.org/not-a-gold-source"\n'
            'D = "https://in.investing.com/currencies/usd-inr"\n')
        (pkg / "catalog_seed.py").write_text(
            'ROWS = [("A21", "Kitco", "https://www.kitco.com/charts/gold"), ("C12", "CME", "https://www.cmegroup.com/x")]\n')
        (pkg / "links.py").write_text(
            'LINKS = [\n'
            '    {"label": "MCX circulars", "href": "https://www.mcxindia.com/circulars/all-circulars"},\n'
            '    # link-only: the owner opens it in a browser\n'
            '    "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",\n'
            ']\n'
            'FETCHED_ANYWAY = "https://prices.lbma.org.uk/json/gold_pm.json"\n')
        (pkg / "hosts.py").write_text(                       # the B1 wrapper: an allowlist AND a denylist of bare hosts
            'ALLOWED_HOSTS: frozenset[str] = frozenset({"ftp.cmegroup.com", "query1.finance.yahoo.com"})\n'
            'FORBIDDEN_HOST_FRAGMENTS: tuple[str, ...] = (\n'
            '    "www.cmegroup.com", "mcxindia.com",\n'
            '    "kitco.com",\n'
            ')\n'
            'REFUSED = "https://stooq.com/q/d/?s=xauusd"          # a denylist needs a NAME: this one is fetched\n')
        scan = scan_hosts(sorted(pkg.glob("*.py")), tmp_path)
        assert scan.fetched["gold/ingest_cot.py"] == {"publicreporting.cftc.gov", "ftp.cmegroup.com",
                                                      "query2.finance.yahoo.com", "127.0.0.1"}
        assert "gold/ingest_cot.py" not in scan.linked and "gold/ingest_cot.py" not in scan.denied
        assert scan.fetched["gold/hosts.py"] == {"ftp.cmegroup.com", "query1.finance.yahoo.com", "stooq.com"}
        assert scan.denied["gold/hosts.py"] == {"www.cmegroup.com", "mcxindia.com", "kitco.com"}
        assert scan.forbidden == [("gold/hosts.py", 6, "stooq.com"), ("gold/ingest_bad.py", 1, "www.kitco.com"),
                                  ("gold/ingest_bad.py", 4, "in.investing.com"), ("gold/links.py", 6, "prices.lbma.org.uk")]
        assert scan.not_allowlisted == [("gold/ingest_bad.py", 3, "example.org")]
        assert scan.fred_rest == [("gold/ingest_bad.py", 2)] and scan.reads_fred_key is False
        assert scan.linked["gold/catalog_seed.py"] == {"www.kitco.com", "www.cmegroup.com"}
        assert scan.linked["gold/links.py"] == {"www.mcxindia.com", "www.cmegroup.com"}
        (pkg / "ingest_bad.py").write_text('import os\nKEY = os.environ.get("FRED_API_KEY")\nB = "https://api.stlouisfed.org/fred"\n')
        one = scan_hosts([pkg / "ingest_bad.py"], tmp_path)
        assert one.reads_fred_key is True and one.fred_key_files == {"gold/ingest_bad.py"} and one.fred_rest_without_key() == []

    def test_fred_key_exempts_only_the_file_that_reads_it(self, tmp_path: Path):
        """A FRED_API_KEY read in a.py does not license the REST host in b.py (wave 1b: per file, not scan-wide)."""
        (tmp_path / "a.py").write_text('import os\nKEY = os.environ.get("FRED_API_KEY")\n')
        (tmp_path / "b.py").write_text('B = "https://api.stlouisfed.org/fred/series/observations"\n')
        (tmp_path / "c.py").write_text('# FRED_API_KEY is read elsewhere (a comment is not a read)\n'
                                       'C = "https://api.stlouisfed.org/fred/series"\n')
        scan = scan_hosts(sorted(tmp_path.glob("*.py")), tmp_path)
        assert scan.fred_key_files == {"a.py"} and scan.reads_fred_key is True
        assert scan.fred_rest == [("b.py", 1), ("c.py", 2)] and scan.fred_rest_without_key() == [("b.py", 1), ("c.py", 2)]
        (tmp_path / "b.py").write_text('import os\nK = os.getenv("FRED_API_KEY")\nB = "https://api.stlouisfed.org/fred"\n')
        assert scan_hosts(sorted(tmp_path.glob("*.py")), tmp_path).fred_rest_without_key() == [("c.py", 2)]

    def test_link_rule_reads_ast_names_and_comments_never_the_literal_itself(self, tmp_path: Path):
        """Wave 1b: a URL whose PATH says 'links' or 'href' is still fetched; a `# link` comment (same line or the line
        above, tokenised: a '#' inside a string is not a comment) or a link-named AST context exempts it."""
        (tmp_path / "m.py").write_text(
            'A = "https://www.kitco.com/links.html"\n'                             # 1: path text is not a marker
            'B = "https://www.kitco.com/x?href=1#link"\n'                           # 2: the string\'s own '#link' neither
            'C = "https://stooq.com/q/"  # link-only\n'                             # 3: comment, same line
            '# see the link in the UI\n'                                             # 4
            'D = "https://goldprice.org/"\n'                                         # 5: comment above
            'E = "https://investing.com/"  # blinker, hyperlinks: not the word\n'   # 6: 'blinker'/'hyperlinks' are not it
            'F_LINK = "https://www.mcxindia.com/circulars"\n'                        # 7: AST name
            'G = {"href": "https://prices.lbma.org.uk/x", "fetch": "https://www.cmegroup.com/y"}\n'   # 8
            'H = "https://www.kitco.com/z"\n'                                       # 9: fetched; the next line\'s comment
            '# link-only applies to I, not to H\n'                                   # 10: is not "above" H
            'I = "https://www.kitco.com/w"\n')                                       # 11
        scan = scan_hosts([tmp_path / "m.py"], tmp_path)
        assert [(n, h) for _, n, h in scan.forbidden] == [(1, "www.kitco.com"), (2, "www.kitco.com"), (6, "investing.com"),
                                                           (8, "www.cmegroup.com"), (9, "www.kitco.com")]
        assert scan.linked["m.py"] == {"stooq.com", "goldprice.org", "www.mcxindia.com", "prices.lbma.org.uk", "www.kitco.com"}
        assert comment_lines('x = "#notacomment"  # real\ny = 1\n# alone\n') == {1: "# real", 3: "# alone"}

    def test_strip_ts_comments_blanks_line_block_and_jsx_comments_but_not_strings(self):
        src = ("const u = 'http://x/y' // trailing\n"
               "/* block\n   spanning */ const v = \"a /* not */ b\"\n"
               "{/* <GoldPreOpen /> */}\n"
               "const t = `tpl // not a comment`\n"
               "// <Panel title=\"Gold open\">\n"
               "<Line />\n")
        out = strip_ts_comments(src)
        assert out.count("\n") == src.count("\n")                                  # line numbers survive
        assert "'http://x/y'" in out and "trailing" not in out and "spanning" not in out
        assert '"a /* not */ b"' in out and "`tpl // not a comment`" in out
        assert "GoldPreOpen" not in out and "Gold open" not in out and "<Line />" in out

    def test_bare_host_needs_a_public_suffix(self):
        assert bare_host("ftp.cmegroup.com") == "ftp.cmegroup.com" and bare_host(" WWW.Kitco.COM ") == "www.kitco.com"
        assert bare_host("ocean.nivel.bazg.admin.ch") and bare_host("nfs.faireconomy.media") and bare_host("pib.gov.in")
        for not_a_host in ("gold.http.get", "gold.cot.ingested", "gold.store", "ui-api.gold", "GCZ26.CMX", "INR=X",
                           "GC=F", "localhost", "a.b.c.d.e.xyz", "", "no dots", "1.2"):
            assert bare_host(not_a_host) is None, not_a_host

    def test_code_strings_skips_docstrings_but_keeps_fstring_parts(self):
        src = '"""mod doc https://www.kitco.com"""\nclass A:\n    """cls doc"""\n    def f(self):\n        """fn doc"""\n' \
              '        return f"https://{host}.finance.yahoo.com/v8/finance/chart/{s}", "x"\n'
        values = [v for _, v, _ in code_strings(src)]
        assert "x" in values and any(".finance.yahoo.com/v8/finance/chart/" in v for v in values)
        assert not any("kitco" in v or "doc" in v for v in values)

    def test_code_strings_context_names_assignment_keyword_dict_key_and_call(self):
        src = ('FORBIDDEN: tuple[str, ...] = ("a.com",)\n'
               'LINKS = [{"href": "b.com"}]\n'
               'x = ftplib.FTP("c.com", timeout=20)\n'
               'client.get(url="d.com")\n'
               'y = ("e.com",)\n'
               'def f():\n    return "g.com"\n')
        ctx = {v: c for _, v, c in code_strings(src)}
        assert ctx["a.com"] == "FORBIDDEN" and ctx["b.com"] == "href LINKS" and ctx["c.com"] == "FTP x"
        assert ctx["d.com"] == "url" and ctx["e.com"] == "y" and ctx["g.com"] == ""

    def test_gold_preopen_render_counter_prunes_builds_and_matches_whole_tag(self, tmp_path: Path):
        (tmp_path / "components" / "gold").mkdir(parents=True)
        (tmp_path / "components" / "gold" / "GoldPage.tsx").write_text("export const X = () => <GoldPreOpen />\n")
        (tmp_path / "components" / "Other.tsx").write_text("<GoldPreOpenDesk /> // a different component\n")
        (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
        (tmp_path / "node_modules" / "pkg" / "a.tsx").write_text("<GoldPreOpen />\n")
        (tmp_path / "dist").mkdir()
        (tmp_path / "dist" / "b.tsx").write_text("<GoldPreOpen/>\n")
        (tmp_path / ".next").mkdir()
        (tmp_path / ".next" / "c.tsx").write_text("<GoldPreOpen>\n")
        (tmp_path / "components" / "Brief.tsx").write_text("{/* was: <GoldPreOpen /> */}\n// <GoldPreOpen />\n<Line />\n")
        hits = gold_preopen_renders(walk_sources(tmp_path, (".tsx", ".ts")))
        assert [(p.name, i) for p, i in hits] == [("GoldPage.tsx", 1)]                 # commented renders do not count
        (tmp_path / "components" / "CommodityTab.tsx").write_text("// moved\n<GoldPreOpen />\n")
        assert [(p.name, i) for p, i in gold_preopen_renders(walk_sources(tmp_path, (".tsx", ".ts")))] == \
            [("CommodityTab.tsx", 2), ("GoldPage.tsx", 1)]

    def test_brief_rules_reject_the_old_panel_and_accept_one_line(self):
        old = ("const gold = useLoad<Gold>(() => getGoldPreOpen({}))\n"
               "const goldLog = useLoad<{ rows: GoldLogRow[] }>(() => getGoldLog(300))\n"
               '<Panel title="Gold open (MCX)" subtitle={g ? `${g.contract.name}` : "pre-open desk"} accent={T.amber}>\n')
        bad = brief_violations(old)
        assert any("getGoldPreOpen" in b for b in bad) and any("getGoldLog" in b for b in bad)
        assert any("gold panel" in b for b in bad) and any("0 times" in b for b in bad)
        new = ("import { getGoldHealthLine, type GoldHealthLine } from '@/lib/api'\n"
               "const goldLine = useLoad<GoldHealthLine>(() => getGoldHealthLine())\n"
               '<Line k="Gold open" v={goldLine.data?.line ?? "—"} />\n')
        assert brief_violations(new) == []
        assert brief_violations("const a = fetch('/api/gold/health?window=W')\n") == []
        assert brief_violations("const line = useGoldHealthLine()\n") == []      # a hook counts as the one read
        twice = new + "const again = useLoad(() => getGoldHealthLine())\n"
        assert any("2 times" in b for b in brief_violations(twice))
        # comment-proof: a commented-out retired call / panel / second read is not code; a commented-out only read is none
        assert brief_violations(new + "// const old = getGoldPreOpen({})\n{/* <Panel title=\"Gold open (MCX)\"> */}\n"
                                "/* const again = getGoldHealthLine() */\n") == []
        assert any("0 times" in b for b in brief_violations("// const line = useGoldHealthLine()\n"))

    def test_commodity_rules(self):
        assert commodity_violations("import { GoldPreOpen } from '@/components/GoldPreOpen'\n<GoldPreOpen />\n")
        assert any("gold desk" in b for b in commodity_violations('subtitle="MCX gold pre-open desk · global futures"\n'))
        assert commodity_violations('subtitle="global futures (USD) · EIA energy fundamentals · FRED context"\n') == []
        # comment-proof: the words in a comment (the PM once had to reword one) and a commented-out import are not code
        assert commodity_violations("// the gold pre-open desk moved to GOLD; <GoldPreOpen /> and GoldAccuracyLog live there\n"
                                    "/* import { GoldPreOpen } from '@/components/GoldPreOpen' */\n"
                                    'subtitle="global futures (USD)"\n') == []
        assert commodity_violations("const s = `MCX gold pre-open desk` // not the comment\n")

    def test_gold_router_rules(self):
        good = "from routers.gold_preopen import _yahoo_bars_cached, fair_open\n"
        assert gold_router_violations(good) == []
        assert gold_router_violations("from routers import gold_preopen as gp\nasync def f():\n    return await gp._yahoo_bars_cached('GC=F')\n") == []
        assert gold_router_violations("from routers.gold_preopen import (\n    _yahoo_bars_cached,\n    fair_open,\n)\n") == []
        # composition through the desk model (what routers/gold.py does today) satisfies the positive rule
        assert gold_router_violations("from routers import gold_preopen as gp\nasync def f():\n    return await gp._gold_preopen(1, 2)\n") == []
        assert gold_router_violations("import routers.gold_preopen as pre\nx = pre.fair_open(1)\n") == []
        bad = gold_router_violations('async def f(client):\n    return await client.get("https://query1.finance.yahoo.com/v8/finance/chart/GC=F")\n')
        assert any("fifth fetcher" in b for b in bad) and any("does not compose" in b for b in bad)
        assert any("uncached" in b for b in gold_router_violations("from routers import gold_preopen as gp\n"
                                                                    "x = gp._yahoo_bars_cached('a'); y = gp._yahoo_bars(client, 'b')\n"))
        assert any("yfinance" in b for b in gold_router_violations(good + "import yfinance as yf\n"))
        # comment-proof (wave 1b): a docstring or comment naming the fetcher is not composition; one naming Yahoo is no fetcher
        doc_only = '"""composes gold_preopen._yahoo_bars_cached"""\nfrom routers import gold_preopen as gp\nx = gp.IST\n'
        assert any("does not compose" in b for b in gold_router_violations(doc_only))
        assert gold_router_violations(good + "# never query1.finance.yahoo.com here; _yahoo_bars( is the uncached one\n") == []
        assert any("does not parse" in b for b in gold_router_violations("def (:\n"))

    def test_yahoo_literal_counter_ignores_tests_comments_and_docstrings(self, tmp_path: Path):
        (tmp_path / "routers").mkdir()
        (tmp_path / "routers" / "a.py").write_text('u = "https://query1.finance.yahoo.com/x"\nv = "https://query2.finance.yahoo.com/y"\n')
        (tmp_path / "routers" / "b.py").write_text('"""talks about query1.finance.yahoo.com"""\n# and query2.finance.yahoo.com\nx = 1\n')
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_a.py").write_text('u = "https://query1.finance.yahoo.com/x"\n')
        assert yahoo_literal_counts(tmp_path) == {"a.py": 2}

    def test_real_ui_api_literal_baseline_is_the_documented_four(self):
        """The 'existing four' of T9 are real today; if this fails, update YAHOO_LITERAL_FILES_TODAY deliberately."""
        need(UI_API / "routers", "ui-api")
        found = yahoo_literal_counts(UI_API)
        assert {k: v for k, v in found.items() if k in YAHOO_LITERAL_FILES_TODAY} == YAHOO_LITERAL_FILES_TODAY

    def test_need_fails_instead_of_skipping(self, tmp_path: Path):
        with pytest.raises(pytest.fail.Exception, match="missing — delivered by B1"):
            need(ROOT / "services" / "data-service" / "gold" / "no-such-file.py", "B1 data")
