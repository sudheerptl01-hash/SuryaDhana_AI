"""Live program gates (reports/live_nse; the owner, 5 Nov 2026: "i need all the data to be live from the nse ... in all
panes and all pages"). The contract (PM-fixed) is in the module constants below; the inventory is
reports/live_nse/L-INVENTORY/REPORT.md §5 (92 panes), the capacity numbers reports/live_nse/L-CAPACITY.

**Static** (file reading, no imports of the apps):

* S1 ``no Yahoo for an NSE display price`` — a cross-module call graph of services/ui-api/routers (AST: plain calls,
  ``functools.partial`` references, ``from routers.x import y as z``, ``import routers.x as m`` + ``m.f``, class methods
  over-approximated). The live routes (``/api/live/*``, ``/api/quotes/ticks`` + ``/live``) reach no Yahoo fetcher and
  do reach data-service ``/live/quotes``; every call site that hands an NSE symbol (an argument built with ``".NS"``) to a
  Yahoo-reaching function goes through ``news_scanner.get_quotes`` only (alerts D9, results-reacting D10), and
  ``get_quotes`` reaches the live service (its ``.NS`` answer is proven behaviourally in B-API); negative control: the same
  graph sees Yahoo behind ``/api/news-scanner/chart`` and ``/api/commodity/overview``. data-service: the ``/live/*``
  handlers and live_quotes.py / live_ticks.py carry no Yahoo name or host and no Breeze REST call; the NSE fallback
  poller's cadences never go under L-CAPACITY's floors; LIVE_TICKS stays default OFF.
* S2 ``every live pane renders a SourceChip`` — each yes-breeze / yes-nse-api row of the inventory: its UI file renders
  ``<SourceChip``, a ``<Panel … source=…>``, the header's ``data-feed`` chip or the stock window's ``data-sd-price``
  marker, or every render of its component sits inside a sourced ``<Panel>`` (file level: per-pane truth is the browser
  check in scripts/ui_audit.py).
* S3 ``the live hook is adopted`` — the 15 price panes read ``ui/lib/liveQuotes.ts`` (a hook imported from THAT module and
  called; AppContext's same-named hook does not count) and take their chip from the live rows; deferrals go in
  ``HOOK_DEFERRED`` with a reason (a ratchet); the hover card, the stock window and the header can never be deferred; the
  hook calls ``/api/live/quotes`` and never Yahoo; the hover card prints the row's source/time line.
* S4 ``NSE website data never reads LIVE`` — ``sourceOf(…, {source: 'NSE…', live: …})`` sites that can read LIVE (NSE's
  website is 34–172 s behind: L-INVENTORY §1, L-CAPACITY §3): 8 files before the build, 0 after; a ratchet at zero.

**Behavioural** (fakes only: no socket, no Breeze, no NSE, no Yahoo, no live stack, no data/ write):

* B-TICKS — live_ticks.py on recorded Breeze ticks (5 Nov 2026 10:20–10:34 IST, L-CAPACITY ladder; public market data)
  and the matching NSEScripMaster rows: ticks map to NSE symbols and index names (negative control: the old
  isec/stock_code lookup files every one under ``4.1!…``); get_names' fallback takes the first token of the same company;
  the cap (101..300), pins first and never evicted, TTL eviction, most-recent-first overflow, a bounded ledger with the
  switch off.
* B-QUOTES — live_quotes.LiveQuotes on the real LiveTicks + a fake NSE client + a fake EOD reader: Breeze tick ≤ 5 s =
  live; an old tick without a healthy socket is delayed then stale; a quiet name on a healthy socket may read live only
  with a "quiet" reason and never past 120 s (LV-DATA's rule, a contract deviation recorded in the notes); NSE website
  rows delayed ≤ 90 s then stale, never live; the poller paces itself; EOD stale during the session, unavailable without
  one; CLOSE after 15:30 with the session date (today's last trade, then the stored close); weekend and pre-open states;
  no network and no Breeze REST on the request path; pins only while open and they reach the tick engine; /live/status
  keys; the two routes on the real data-service app (subprocess).
* B-API — ui-api in a subprocess (TestClient, no lifespan, every socket refused, httpx answered by a fake data-service,
  Yahoo hosts a tripwire): ``/api/news-scanner/quotes`` answers ``.NS`` from the live service with zero Yahoo requests
  (live, delayed and down), keeps its body keys and adds source/state/age; positive control: a US symbol still reaches
  Yahoo; negative control: LV-API's rollback lever ``LIVE_QUOTES_NSE=0`` puts '.NS' back on Yahoo and the tripwire sees it;
  ``/api/quotes/ticks`` and ``/api/live/quotes`` never reach Yahoo; three reads inside 2 s cost one data-service request;
  the server price-alert check prices an NSE name from the live service; the push channel's per-client queue is
  bounded and drops the oldest.

The fixture tests (``TestGateMachinery``) prove each scanner on synthetic sources and must be green at all times.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import textwrap
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "ui"
UI_API = ROOT / "services" / "ui-api"
ROUTERS = UI_API / "routers"
DATA_SVC = ROOT / "services" / "data-service"
INVENTORY = ROOT / "reports" / "live_nse" / "L-INVENTORY" / "REPORT.md"
LIVE_HOOK = UI / "lib" / "liveQuotes.ts"
P = sys.executable

# ── the contract (reports/live_nse build script, CONTRACT) ─────────────────────────────────────────────────────────
QUOTE_KEYS = {"price", "change", "change_pct", "prev_close", "open", "day_high", "day_low", "volume", "value_cr", "bid",
              "ask", "ltt", "source", "age_s", "state"}
SOURCES = {"breeze_ws", "nse_api", "eod"}
STATES = {"live", "delayed", "stale", "closed", "unavailable"}
MARKET_STATES = {"open", "pre-open", "closed"}
FEED_STATES = {"OFF", "CONNECTING", "LIVE", "DEGRADED", "DISCONNECTED"}
STATUS_KEYS = {"state", "subscribed", "ticks_per_min", "last_tick_age_s", "cap", "breeze_session", "nse_fallback"}
LIVE_FRESH_S = 5.0                     # a Breeze tick at most this old is live
NSE_DELAYED_MAX_S = 90.0               # an NSE website row at most this old is delayed
CAP_MIN, CAP_MAX = 101, 300            # index + NIFTY 50 members + NIFTY BANK + holdings … ≤ the contract's 300
MAX_REQUEST_SYMBOLS = 300
LIVE_ROUTES = ("/api/live/quotes", "/api/live/status", "/api/quotes/ticks", "/api/quotes/live")

UI_SKIP_DIRS = frozenset({"node_modules", "dist", "out", ".next", "__tests__"})


def need(path: Path, owner: str) -> None:
    """Fail, never skip, when a source the gate needs is absent (names the builder who delivers it)."""
    if not path.exists():
        pytest.fail(f"{path.relative_to(ROOT)} is missing — delivered by {owner} (reports/live_nse contract); the gate "
                    f"stays red until it lands", pytrace=False)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# the inventory (L-INVENTORY §5)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Pane:
    rank: str
    page: str
    pane: str
    ui_files: tuple[str, ...]
    routes: str
    live_capable: str


def parse_inventory(text: str) -> list[Pane]:
    """The §5 table → rows. ``ui_files`` keeps every repo path in the UI-file cell (``a.tsx (in B.tsx)`` → ``a.tsx``;
    ``a.tsx, b.ts`` → both); ``**yes-breeze**`` → ``yes-breeze``."""
    sec = text.split("## 5. Full inventory", 1)[1].split("\n## ", 1)[0]
    out: list[Pane] = []
    for line in sec.splitlines():
        if not line.startswith("| ") or line.startswith("| P |") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) != 9:
            continue
        files = tuple(m.group(0) for m in re.finditer(r"(?:ui|services)/[\w./\-*]+\.(?:tsx|ts|py)", cells[3]))
        out.append(Pane(cells[0], cells[1], cells[2], files, cells[4], cells[7].strip("*").strip()))
    return out


@pytest.fixture(scope="module")
def inventory() -> list[Pane]:
    need(INVENTORY, "L-INVENTORY")
    return parse_inventory(INVENTORY.read_text(encoding="utf-8"))


def live_rows(rows: Iterable[Pane]) -> list[Pane]:
    return [r for r in rows if r.live_capable in ("yes-breeze", "yes-nse-api")]


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# S1 — the ui-api call graph (pure helpers, proven on fixtures in TestGateMachinery)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
YAHOO_HOST = re.compile(r"finance\.yahoo\.com|query[12]\.finance\.yahoo")
YAHOO_NAMES = {"yfinance", "DirectYahooProvider", "get_yfinance"}
LIVE_SERVICE_TEXT = re.compile(r"/live/quotes\b")
YAHOO_API_HOST = re.compile(r"query[12]\.finance\.yahoo\.com")


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


@dataclass
class Module:
    name: str
    tree: ast.Module
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(default_factory=dict)   # 'f' / 'Class.m'
    classes: dict[str, list[str]] = field(default_factory=dict)             # class → its method keys
    imported: dict[str, tuple[str, str]] = field(default_factory=dict)      # local name → (module, function)
    module_alias: dict[str, str] = field(default_factory=dict)              # local alias → module
    doc_ids: set[int] = field(default_factory=set)


def load_module(name: str, src: str, package: str = "routers") -> Module:
    tree = ast.parse(src)
    m = Module(name, tree, doc_ids=_docstring_ids(tree))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            m.functions[node.name] = node
        elif isinstance(node, ast.ClassDef):            # methods are graph nodes too ('LiveQuotesHub._fetch')
            keys = []
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    m.functions[f"{node.name}.{item.name}"] = item
                    keys.append(f"{node.name}.{item.name}")
            m.classes[node.name] = keys
    for anode in ast.walk(tree):                        # imports anywhere (routers import inside functions too)
        if isinstance(anode, ast.ImportFrom) and anode.module:
            mod = anode.module
            if mod == package:                          # from routers import gold_preopen as gp
                for a in anode.names:
                    m.module_alias[a.asname or a.name] = a.name
            elif mod.startswith(package + "."):         # from routers.news_scanner import get_quotes as _y
                target = mod.split(".", 1)[1]
                for a in anode.names:
                    m.imported[a.asname or a.name] = (target, a.name)
        elif isinstance(anode, ast.Import):
            for a in anode.names:
                if a.name.startswith(package + "."):    # import routers.gold_preopen as gp
                    m.module_alias[a.asname or a.name.split(".")[-1]] = a.name.split(".", 1)[1]
    return m


def edges(m: Module, fn: str) -> set[tuple[str, str]]:
    """Functions ``fn`` calls or references (a reference covers ``functools.partial(f, …)`` and ``Depends(f)``).
    Classes over-approximate (this is a reachability guard, so more reach is the safe side): naming a class reaches all
    its methods; ``x.meth`` reaches every method called ``meth`` of the module's classes; ``alias.f`` reaches module
    ``alias``'s function ``f`` (or its class ``f``'s methods)."""
    out: set[tuple[str, str]] = set()
    methods_by_name: dict[str, list[str]] = {}
    for keys in m.classes.values():
        for k in keys:
            methods_by_name.setdefault(k.split(".", 1)[1], []).append(k)
    for node in ast.walk(m.functions[fn]):
        if isinstance(node, ast.Name):
            if node.id in m.functions and node.id != fn:
                out.add((m.name, node.id))
            elif node.id in m.classes:
                out |= {(m.name, k) for k in m.classes[node.id]}
            elif node.id in m.imported:
                out.add(m.imported[node.id])
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in m.module_alias:
                out.add((m.module_alias[node.value.id], node.attr))
            for k in methods_by_name.get(node.attr, []):
                if k != fn:
                    out.add((m.name, k))
    return out


def _texts(m: Module, fn: str) -> Iterable[str]:
    for node in ast.walk(m.functions[fn]):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in m.doc_ids:
            yield node.value


def is_yahoo_sink(m: Module, fn: str) -> bool:
    """A function that talks to Yahoo itself: a Yahoo host in a code string, or a yfinance name."""
    if any(YAHOO_HOST.search(t) for t in _texts(m, fn)):
        return True
    for node in ast.walk(m.functions[fn]):
        ident = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
        if ident in YAHOO_NAMES:
            return True
    return False


class CallGraph:
    def __init__(self, modules: dict[str, Module]):
        self.modules = modules
        self._reach: dict[tuple[str, str], set[tuple[str, str]]] = {}

    @classmethod
    def from_dir(cls, routers: Path) -> CallGraph:
        mods = {p.stem: load_module(p.stem, p.read_text(encoding="utf-8")) for p in sorted(routers.glob("*.py"))}
        return cls(mods)

    def exists(self, key: tuple[str, str]) -> bool:
        if key[0] not in self.modules:
            return False
        mod = self.modules[key[0]]
        return key[1] in mod.functions or key[1] in mod.classes

    def reach(self, key: tuple[str, str]) -> set[tuple[str, str]]:
        """Every function reachable from ``key`` (itself included), across router modules."""
        if key in self._reach:
            return self._reach[key]
        seen: set[tuple[str, str]] = set()
        todo = [key]
        while todo:
            k = todo.pop()
            if k in seen or not self.exists(k):
                continue
            mod = self.modules[k[0]]
            if k[1] in mod.classes:                     # an imported class name → all its methods there
                todo.extend((k[0], meth) for meth in mod.classes[k[1]])
                continue
            seen.add(k)
            todo.extend(edges(mod, k[1]))
        self._reach[key] = seen
        return seen

    def yahoo_sinks(self, key: tuple[str, str]) -> list[str]:
        return sorted(f"{m}.{f}" for m, f in self.reach(key) if is_yahoo_sink(self.modules[m], f))

    def reaches_text(self, key: tuple[str, str], pattern: re.Pattern[str]) -> bool:
        return any(pattern.search(t) for m, f in self.reach(key) for t in _texts(self.modules[m], f))

    def routes(self, prefixes: dict[str, str]) -> dict[str, tuple[str, str]]:
        """Full path → handler, from ``@router.get("/x")`` decorators (``APIRouter(prefix=…)`` honoured) and the
        ``include_router`` prefixes of main.py (``prefixes``: module → prefix)."""
        out: dict[str, tuple[str, str]] = {}
        for name, m in self.modules.items():
            router_prefix: dict[str, str] = {}
            for node in m.tree.body:
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and \
                        getattr(node.value.func, "id", getattr(node.value.func, "attr", "")) == "APIRouter":
                    pre = next((k.value.value for k in node.value.keywords if k.arg == "prefix"
                                and isinstance(k.value, ast.Constant)), "")
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            router_prefix[t.id] = str(pre)
            for fn_name, fn in m.functions.items():
                for dec in fn.decorator_list:
                    if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                            and dec.func.attr in ("get", "post", "put", "delete", "websocket", "api_route")):
                        continue
                    if not (dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str)):
                        continue
                    rname = dec.func.value.id if isinstance(dec.func.value, ast.Name) else "router"
                    base = prefixes.get(name if rname == "router" else f"{name}.{rname}", "")
                    out[base + router_prefix.get(rname, "") + dec.args[0].value] = (name, fn_name)
        return out


def include_prefixes(main_src: str) -> dict[str, str]:
    """``app.include_router(quotes.router, prefix="/api/quotes")`` → {"quotes": "/api/quotes"}; an alias import
    (``from routers import alerts as price_alerts``) maps back to the module; a second router object of a module
    (``markets.attribution_router``) is keyed ``markets.attribution_router``."""
    tree = ast.parse(main_src)
    alias: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "routers":
            for a in node.names:
                alias[a.asname or a.name] = a.name
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "include_router" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
                mod = alias.get(arg.value.id, arg.value.id)
                key = mod if arg.attr == "router" else f"{mod}.{arg.attr}"
                pre = next((k.value.value for k in node.keywords if k.arg == "prefix" and isinstance(k.value, ast.Constant)), "")
                out.setdefault(key, str(pre))
    return out


def nse_symbol_calls(graph: CallGraph) -> list[tuple[str, str, int, tuple[str, str]]]:
    """Call sites that hand an NSE symbol to a Yahoo-reaching function: the call's arguments contain a ``".NS"``
    literal (``f"{s}.NS"``, ``",".join(f"{s}.NS" for …)``) or a name bound earlier in the same function to such an
    expression (``yahoo = {sym: f"{sym}.NS" …}`` then ``get_quotes(symbols=",".join(yahoo.values()))``).
    → [(module, function, line, callee)]."""
    hits: list[tuple[str, str, int, tuple[str, str]]] = []

    def has_ns(expr: ast.AST, tainted: set[str]) -> bool:
        for n in ast.walk(expr):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.endswith(".NS"):
                return True
            if isinstance(n, ast.Name) and n.id in tainted:
                return True
        return False

    for mname, m in graph.modules.items():
        for fname, fn in m.functions.items():
            tainted: set[str] = set()
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign) and has_ns(node.value, tainted):
                    tainted |= {t.id for t in node.targets if isinstance(t, ast.Name)}
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                callee: tuple[str, str] | None = None
                if isinstance(f, ast.Name):
                    callee = (mname, f.id) if f.id in m.functions else m.imported.get(f.id)
                elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in m.module_alias:
                    callee = (m.module_alias[f.value.id], f.attr)
                if callee is None or not graph.exists(callee) or not graph.yahoo_sinks(callee):
                    continue
                args = list(node.args) + [k.value for k in node.keywords]
                if any(has_ns(a, tainted) for a in args):
                    hits.append((mname, fname, node.lineno, callee))
    return hits


# the one Yahoo-reaching entry point allowed to receive NSE symbols: its .NS branch answers from the live service
NSE_SAFE_ENTRY = ("news_scanner", "get_quotes")


@pytest.fixture(scope="module")
def graph() -> CallGraph:
    need(ROUTERS, "ui-api")
    return CallGraph.from_dir(ROUTERS)


@pytest.fixture(scope="module")
def routes(graph: CallGraph) -> dict[str, tuple[str, str]]:
    return graph.routes(include_prefixes((UI_API / "main.py").read_text(encoding="utf-8")))


class TestNoYahooForNsePricesS1:
    """S1: no Yahoo call is reachable for an NSE symbol's display price."""

    def test_the_route_table_resolves(self, routes: dict[str, tuple[str, str]]):
        assert routes.get("/api/news-scanner/quotes") == ("news_scanner", "get_quotes")
        assert routes.get("/api/alerts/run", (None, None))[0] == "alerts"
        assert len(routes) > 150, len(routes)

    def test_negative_control_the_graph_sees_the_real_yahoo_routes(self, graph: CallGraph,
                                                                   routes: dict[str, tuple[str, str]]):
        """The same graph on routes that DO reach Yahoo (non-NSE by design): a blind scanner would pass S1 vacuously."""
        for path, sink in (("/api/news-scanner/chart/{symbol}", "news_scanner._yahoo_chart"),
                           ("/api/commodity/overview", "commodity._yahoo_chart"),
                           ("/api/news-scanner/quotes", "news_scanner._yahoo_chart")):
            assert path in routes, path
            assert sink in graph.yahoo_sinks(routes[path]), (path, graph.yahoo_sinks(routes[path]))

    @pytest.mark.parametrize("path", LIVE_ROUTES)
    def test_live_routes_exist_and_reach_no_yahoo_fetcher(self, path: str, graph: CallGraph,
                                                          routes: dict[str, tuple[str, str]]):
        if path.startswith("/api/live/"):
            need(ROUTERS / "live.py", "LV-API")
        handler = routes.get(path)
        assert handler is not None, f"{path} has no handler in services/ui-api/routers (LV-API)"
        sinks = graph.yahoo_sinks(handler)
        assert not sinks, f"{path} ({handler[0]}.{handler[1]}) reaches Yahoo: {sinks}"

    def test_live_routes_read_the_data_service_live_quotes(self, graph: CallGraph, routes: dict[str, tuple[str, str]]):
        need(ROUTERS / "live.py", "LV-API")
        for path in ("/api/live/quotes", "/api/quotes/ticks"):
            handler = routes.get(path)
            assert handler and graph.reaches_text(handler, LIVE_SERVICE_TEXT), \
                f"{path} does not reach data-service /live/quotes"

    def test_news_scanner_quotes_reaches_the_live_service(self, graph: CallGraph):
        assert graph.reaches_text(NSE_SAFE_ENTRY, LIVE_SERVICE_TEXT), \
            "news_scanner.get_quotes never reaches /live/quotes: its '.NS' symbols can only be priced by Yahoo"

    def test_nse_symbols_reach_yahoo_only_through_the_live_aware_entry(self, graph: CallGraph):
        bad = [f"{m}.{f}:{line} → {c[0]}.{c[1]}" for m, f, line, c in nse_symbol_calls(graph)
               if c != NSE_SAFE_ENTRY and m != NSE_SAFE_ENTRY[0]]
        assert not bad, f"an NSE symbol is handed straight to a Yahoo fetcher: {bad}"

    def test_the_known_nse_callers_still_pass_through_get_quotes(self, graph: CallGraph):
        """The server-side price paths the inventory flagged (D9 alerts, D10 results-reacting) price NSE names through
        ``get_quotes`` — so B-API's proof that ``get_quotes`` answers ``.NS`` from the live service covers them."""
        callers = {(m, f) for m, f, _, c in nse_symbol_calls(graph) if c == NSE_SAFE_ENTRY}
        assert any(m == "alerts" for m, _ in callers), callers
        assert any(m == "markets" for m, _ in callers), callers
        assert not any(m in ("quotes", "live") for m, _ in callers), f"the live routes price through Yahoo's entry: {callers}"

    def test_data_service_live_modules_have_no_yahoo_and_no_breeze_rest_quote(self):
        need(DATA_SVC / "live_quotes.py", "LV-DATA")
        for name in ("live_quotes.py", "live_ticks.py"):
            src = (DATA_SVC / name).read_text(encoding="utf-8")
            tree = ast.parse(src)
            docs = _docstring_ids(tree)
            texts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                     and id(n) not in docs]
            assert not [t for t in texts if YAHOO_HOST.search(t)], f"{name}: Yahoo host literal"
            idents = {n.id if isinstance(n, ast.Name) else n.attr for n in ast.walk(tree)
                      if isinstance(n, ast.Name | ast.Attribute)}
            assert not (idents & YAHOO_NAMES), f"{name}: Yahoo names {idents & YAHOO_NAMES}"
            rest = {"get_quotes", "get_option_chain_quotes", "get_historical_data", "get_historical_data_v2"} & {
                n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
            assert not rest, f"{name}: Breeze REST call on the live path: {rest} (quota: websocket only)"

    def test_data_service_live_routes_reach_no_yahoo(self):
        """data-service main.py: the /live/* handlers and every main.py function they reach (G5's walk, here through
        the same graph) carry no Yahoo name or host."""
        main = load_module("main", (DATA_SVC / "main.py").read_text(encoding="utf-8"), package="__no_package__")
        g = CallGraph({"main": main})
        r = g.routes({})
        for path in ("/live/quotes", "/live/status", "/live/ticks"):
            assert path in r, f"data-service has no {path} route (LV-DATA)"
            assert not g.yahoo_sinks(r[path]), (path, g.yahoo_sinks(r[path]))
        assert len(g.reach(r["/live/quotes"])) >= 2, g.reach(r["/live/quotes"])      # the walk is not vacuous

    def test_nse_poller_cadences_never_go_under_the_l_capacity_floors(self, lq: Any, monkeypatch: pytest.MonkeyPatch):
        """An Akamai block would blank the NSE fallback for every pane: allIndices ≥ 15 s, each heatmap list ≥ 60 s,
        the per-symbol quote ≥ 60 s, ≥ 1.2 s between NSE calls; an env override can slow them, never speed them up."""
        assert lq.ALLINDICES_TTL_S >= 15 and lq.HEATMAP_TTL_S >= 60 and lq.NEXTAPI_TTL_S >= 60 and lq.NSE_GAP_S >= 1.2
        monkeypatch.setenv("LIVE_NSE_HEATMAP_TTL_S", "5")
        assert lq._env_floor("LIVE_NSE_HEATMAP_TTL_S", 60.0, 60.0) == 60.0
        monkeypatch.setenv("LIVE_NSE_HEATMAP_TTL_S", "90")
        assert lq._env_floor("LIVE_NSE_HEATMAP_TTL_S", 60.0, 60.0) == 90.0

    def test_live_ticks_kill_switch_still_defaults_off(self):
        src = (DATA_SVC / "live_ticks.py").read_text(encoding="utf-8")
        assert re.search(r'os\.getenv\("LIVE_TICKS",\s*"0"\)\s*==\s*"1"', src), \
            "LIVE_TICKS must stay default OFF in code (the PM flips .env at deploy)"


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# S2 / S3 / S4 — the UI scan
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
def strip_ts_comments(src: str) -> str:
    """TS/TSX with ``//`` and ``/* */`` comments blanked (newlines kept); strings (', ", `) are left alone."""
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


def ts_code(path: Path) -> str:
    return strip_ts_comments(path.read_text(encoding="utf-8"))


CHIP_RENDER = re.compile(r"<SourceChip\b|\bdata-feed=|\bdata-sd-price=|\bdata-sd-chip=")


def _tag_text(src: str, start: int) -> str:
    """The JSX opening tag text starting at ``start`` ('<Panel …>'), braces balanced (a '>' inside {…} is not the end)."""
    depth, i = 0, start
    while i < len(src):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == ">" and depth == 0:
            return src[start:i + 1]
        i += 1
    return src[start:]


def sourced_panel_tags(src: str) -> int:
    """How many ``<Panel …>`` opening tags carry a ``source=`` prop."""
    return sum(1 for m in re.finditer(r"<Panel\b", src) if re.search(r"\bsource=", _tag_text(src, m.start())))


def renders_chip(src: str) -> bool:
    """A file renders a source chip itself: SourceChip, the header feed chip, the stock-window marker, or a sourced
    Panel."""
    return bool(CHIP_RENDER.search(src)) or sourced_panel_tags(src) > 0


def enclosed_in_sourced_panel(parent: str, component: str) -> bool | None:
    """Every ``<Component`` render in ``parent`` sits inside an open ``<Panel … source=…>``. None = not rendered there."""
    uses = [m.start() for m in re.finditer(rf"(?<![\w.$])<{re.escape(component)}\b(?!\s*[|,>\]])", parent)]
    if not uses:
        return None
    events = sorted([(m.start(), "open", m.start()) for m in re.finditer(r"<Panel\b", parent)]
                    + [(m.start(), "close", 0) for m in re.finditer(r"</Panel>", parent)])
    for pos in uses:
        stack: list[int] = []
        for at, kind, start in events:
            if at >= pos:
                break
            if kind == "open":
                tag = _tag_text(parent, start)
                if not tag.rstrip().endswith("/>"):
                    stack.append(start)
            elif stack:
                stack.pop()
        if not stack or not re.search(r"\bsource=", _tag_text(parent, stack[-1])):
            return False
    return True


def component_names(src: str) -> list[str]:
    return re.findall(r"export\s+(?:default\s+)?function\s+([A-Z]\w*)", src) + \
        re.findall(r"export\s+const\s+([A-Z]\w*)\s*=", src)


def ui_sources() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for root in (UI / "components", UI / "app", UI / "lib"):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in UI_SKIP_DIRS and not d.startswith("."))
            for f in filenames:
                if f.endswith((".tsx", ".ts")) and not f.endswith((".check.ts", ".d.ts")):
                    p = Path(dirpath) / f
                    out[p] = strip_ts_comments(p.read_text(encoding="utf-8"))
    return out


def chip_coverage(file: Path, sources: dict[Path, str]) -> tuple[bool, str]:
    """(covered, how) for one UI file: its own chip, or every parent render inside a sourced Panel."""
    src = sources.get(file)
    if src is None:
        return False, "file missing"
    if renders_chip(src):
        return True, "own chip"
    names = component_names(src)
    parents: list[str] = []
    for p, psrc in sources.items():
        if p == file or p.suffix != ".tsx":
            continue                                    # a generic in a .ts module (Promise<IndexIntraday>) is no render
        for name in names:
            enc = enclosed_in_sourced_panel(psrc, name)
            if enc is None:
                continue
            if not enc:
                return False, f"<{name}> rendered outside a sourced Panel in {p.relative_to(ROOT)}"
            parents.append(f"{p.name}<{name}>")
    return (True, "inside " + ", ".join(sorted(set(parents)))) if parents else (False, "no chip and no sourced parent")


# S3: the price panes that must read the live hook (target "Breeze ws tick" for an NSE price in the inventory). The
# other yes-breeze rows go live elsewhere: CHRT / the intraday charts from the tick store, MCXG on an MCX tick (not an
# NSE symbol: outside /live/quotes), the server alert check and "results reacting" through ui-api (S1 + B-API).
HOOK_PANES: dict[str, str] = {
    "ui/components/MarketCommandHeader.tsx": "header NIFTY 50 chip + tape NIFTY / BANK / VIX",
    "ui/components/LiveMonitorBar.tsx": "watchlist line under the header",
    "ui/components/terminal/index.tsx": "TickerLink hover card (the owner's complaint, 5 Nov 10:10)",
    "ui/components/news/NewsTerminal.tsx": "news dock picks' quotes",
    "ui/components/Brief.tsx": "BRF your book + who moved NIFTY",
    "ui/components/WatchMonitor.tsx": "WTCH monitor table",
    "ui/components/IndexContribution.tsx": "MOV who moved the index",
    "ui/components/StockDetailModal.tsx": "stock window price line",
    "ui/components/DecisionDesk.tsx": "DESK holdings Last / P&L",
    "ui/components/DerivativesDesk.tsx": "DERV underlying spot",
    "ui/components/IndexMembers.tsx": "MEMB points today / LTP",
    "ui/components/AlertsCenter.tsx": "ALRT price-alerts table",
    "ui/components/WorldMarkets.tsx": "WEI India row",
    "ui/components/StockTable.tsx": "EQS CMP column",
    "ui/components/PortfolioSummary.tsx": "BRKR day move",
}
# rows not adopted yet: file → reason (ratchet — an adopted row must be removed; the hover card never appears here)
HOOK_DEFERRED: dict[str, str] = {}
NEVER_DEFER = frozenset({"ui/components/terminal/index.tsx", "ui/components/StockDetailModal.tsx",
                         "ui/components/MarketCommandHeader.tsx"})
HOOK_IMPORT = re.compile(r"import\s*(?:type\s+)?\{([^}]*)\}\s*from\s*['\"](?:@/lib|(?:\.\./)+lib|\./lib)/liveQuotes['\"]")


def hook_locals(src: str) -> set[str]:
    """Local names bound to a hook of ui/lib/liveQuotes (``useLiveQuotes`` or ``useLiveQuotes as useNseQuotes``). A
    same-named hook from elsewhere (AppContext's monitor-socket ``useLiveQuotes``) is not the live hook."""
    out: set[str] = set()
    for m in HOOK_IMPORT.finditer(src):
        for part in m.group(1).split(","):
            bits = part.strip().replace("type ", "").split(" as ")
            name, local = bits[0].strip(), bits[-1].strip()
            if re.fullmatch(r"use[A-Z]\w*", name):
                out.add(local)
    return out


def calls_hook(src: str) -> bool:
    return any(re.search(rf"\b{re.escape(n)}\s*(?:<[^>]*>)?\s*\(", src) for n in hook_locals(src))


LIVE_CHIP_USE = re.compile(r"\b(?:sourceFor|lineFor|liveSourceInfo|quoteSource|quoteLine)\s*\(")
# a pane may also use the hook RESULT's own .source (const lq = useLiveQuotes(...); <SourceChip info={lq.source}/>) or a
# destructured `source` from it — never any `.source` (check:LV-GATES major: the bare `.source` matched everything)


def _hook_result_source(src: str) -> bool:
    for m in re.finditer(r"const\s+(\w+)\s*=\s*useLiveQuotes\s*\(", src):
        if re.search(rf"\b{m.group(1)}\.source\b", src):
            return True
    return bool(re.search(r"const\s*\{[^}]*\bsource\b[^}]*\}\s*=\s*useLiveQuotes\s*\(", src))


# the shared kit and ui/lib are imported by EVERY pane: a hook call there must not count as the pane's adoption
# (check:LV-GATES major — 13 of 15 panes passed through ui/components/terminal/index.tsx's HoverCard)
SHARED_KIT = (UI / "components" / "terminal", UI / "lib")


def _local_deps(file: Path, src: str, sources: dict[Path, str]) -> list[str]:
    out: list[str] = []
    for m in re.finditer(r"from\s+['\"](@/components/[\w/]+|\.{1,2}/[\w/]+)['\"]", src):
        spec = m.group(1)
        base = (UI / spec[2:]) if spec.startswith("@/") else (file.parent / spec).resolve()
        for cand in (base.with_suffix(".tsx"), base.with_suffix(".ts"), base / "index.tsx"):
            if any(str(cand).startswith(str(k)) for k in SHARED_KIT):
                continue
            dep = sources.get(cand)
            if dep and re.search(rf"<{re.escape(cand.stem)}\b|<{re.escape(base.name)}\b", src):   # composed only if RENDERED
                out.append(dep)
    return out


def uses_hook(file: Path, sources: dict[Path, str]) -> bool:
    """The file calls a hook it imports from ui/lib/liveQuotes, or renders a component from a local module that does
    (one level)."""
    src = sources.get(file, "")
    if calls_hook(src):
        return True
    if str(file.relative_to(ROOT)) in NEVER_DEFER:          # the header, hover card and stock window call it themselves
        return False
    return any(calls_hook(dep) for dep in _local_deps(file, src, sources))


def derives_live_chip(file: Path, sources: dict[Path, str]) -> bool:
    """The pane's chip / time line comes from the live rows (the hook result's ``source`` / ``sourceFor`` / ``lineFor``,
    or the liveQuotes chip helpers), in the file or a local module it composes — not a chip of its own invention."""
    src = sources.get(file, "")
    if LIVE_CHIP_USE.search(src) or _hook_result_source(src):
        return True
    return any(LIVE_CHIP_USE.search(dep) or _hook_result_source(dep) for dep in _local_deps(file, src, sources)
               if calls_hook(dep) or "liveQuotes" in dep)


# S4: sourceOf(...) sites that can label NSE WEBSITE data LIVE (34-172 s behind, L-INVENTORY §1 / L-CAPACITY §3).
# 5 Nov 2026 baseline before the build: 8 files (CompanyFilings, OptionPricer, OptionChain, MarketMap, PreOpen, Brief,
# LiveMovers, EventCalendar); after LV-UI (5 Nov 11:20): none. A ratchet: a file's count may only go down, and a new
# file starts at zero; an honest chip is `live: false` / the hook's DELAYED <age>. Breeze-sourced live chips are not
# counted.
NSE_LIVE_KNOWN: dict[str, int] = {}


def _call_args(src: str, start: int) -> str:
    """The text of a call's parenthesised arguments starting at the '(' at ``start``."""
    depth, i = 0, start
    while i < len(src):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    return src[start:]


LIVE_LITERAL = re.compile(r"\bstate:\s*['\"]live['\"]")


def live_literals(src: str) -> int:
    """SourceInfo object literals that claim LIVE (``{ state: 'live', … }``) — the pattern sourceOf scanning missed
    (check:LV-GATES major: IvLivePath labelled stored 15-min snapshots LIVE)."""
    return len(LIVE_LITERAL.findall(src))


def nse_live_sites(src: str) -> int:
    """``sourceOf(…, { … source: 'NSE…', live: <anything but false> … })`` calls — an NSE website feed that can read LIVE."""
    n = 0
    for m in re.finditer(r"\bsourceOf\(", src):
        args = _call_args(src, m.end() - 1)
        if not re.search(r"source:\s*(?:[\w.!?]+\s*\?\s*)?['\"`]NSE", args):
            continue
        live = re.search(r"\blive:\s*([^,}]+)", args)
        if live and live.group(1).strip() != "false":
            n += 1
    return n


@pytest.fixture(scope="module")
def sources() -> dict[Path, str]:
    return ui_sources()


class TestSourceChipOnEveryLivePaneS2:
    def test_inventory_is_the_survey(self, inventory: list[Pane]):
        from collections import Counter

        assert len(inventory) == 92
        assert Counter(r.live_capable for r in inventory) == {"yes-breeze": 25, "yes-nse-api": 13, "eod-only": 25,
                                                               "periodic": 10, "n/a": 19}
        assert all(r.ui_files for r in live_rows(inventory)), [r.pane for r in live_rows(inventory) if not r.ui_files]

    def test_every_live_pane_renders_a_source_chip(self, inventory: list[Pane], sources: dict[Path, str]):
        missing: list[str] = []
        checked = 0
        for r in live_rows(inventory):
            for f in r.ui_files:
                if not f.startswith("ui/"):
                    continue                            # server-side rows (alerts.py) are S1 / B-API
                if not f.endswith(".tsx"):
                    continue                            # a data helper (ui/lib/chartData.ts) renders nothing
                checked += 1
                ok, how = chip_coverage(ROOT / f, sources)
                if not ok:
                    missing.append(f"{r.page} · {r.pane[:50]} · {f}: {how}")
        assert checked >= 35, checked
        assert not missing, "live panes without a SourceChip:\n  " + "\n  ".join(missing)


class TestLiveHookAdoptedS3:
    def test_the_hook_exists_and_talks_only_to_the_live_service(self):
        need(LIVE_HOOK, "LV-UI")
        src = ts_code(LIVE_HOOK)
        assert re.search(r"export\s+function\s+useLiveQuotes\b", src), "ui/lib/liveQuotes.ts exports no useLiveQuotes"
        assert "/api/live/quotes" in src or "/live/quotes" in src, "the hook does not call /api/live/quotes"
        assert not re.search(r"news-scanner|yahoo|getNewsQuotes", src, re.IGNORECASE), "the hook reads a Yahoo path"

    def test_hook_panes_are_the_inventory_rows(self, inventory: list[Pane]):
        breeze = {f for r in inventory if r.live_capable == "yes-breeze" for f in r.ui_files}
        assert set(HOOK_PANES) <= breeze, sorted(set(HOOK_PANES) - breeze)
        assert set(HOOK_DEFERRED) <= set(HOOK_PANES) and not (set(HOOK_DEFERRED) & NEVER_DEFER)

    def test_every_price_pane_reads_the_live_hook_or_is_deferred_with_a_reason(self, sources: dict[Path, str]):
        need(LIVE_HOOK, "LV-UI")
        not_adopted = {f for f in HOOK_PANES if not uses_hook(ROOT / f, sources)}
        undeclared = sorted(not_adopted - set(HOOK_DEFERRED))
        stale_deferrals = sorted(set(HOOK_DEFERRED) - not_adopted)
        assert not undeclared, "price panes not on the live hook (adopt, or defer with a reason):\n  " + \
            "\n  ".join(f"{f} — {HOOK_PANES[f]}" for f in undeclared)
        assert not stale_deferrals, f"adopted now — remove from HOOK_DEFERRED: {stale_deferrals}"

    def test_adopted_panes_take_their_chip_from_the_live_rows(self, sources: dict[Path, str]):
        need(LIVE_HOOK, "LV-UI")
        bad = [f for f in HOOK_PANES if f not in HOOK_DEFERRED and not derives_live_chip(ROOT / f, sources)]
        assert not bad, f"panes on the live hook whose chip is not derived from the live rows (source + age): {bad}"

    def test_s3_negative_control_on_the_real_tree(self, sources: dict[Path, str]):
        """Each adopted pane with its OWN hook import and calls stripped must fail uses_hook against today's tree: the
        gate cannot be passed through the shared kit (check:LV-GATES major)."""
        need(LIVE_HOOK, "LV-UI")
        leaked = []
        for f in HOOK_PANES:
            path = ROOT / f
            src = sources.get(path, "")
            if not calls_hook(src):
                continue
            stripped = re.sub(r"^.*from\s+['\"]@/lib/liveQuotes['\"].*$", "", src, flags=re.M)
            stripped = re.sub(r"\buseLiveQuotes\b", "useNothing", stripped)
            mutated = dict(sources); mutated[path] = stripped
            via_rendered = any(calls_hook(dep) for dep in _local_deps(path, stripped, mutated))   # a component it RENDERS
            expected = False if f in NEVER_DEFER else via_rendered
            if uses_hook(path, mutated) != expected:
                leaked.append(f)
        assert not leaked, f"panes whose adoption verdict does not follow their own code + rendered components: {leaked}"
        # the shared kit never counts: the kit's HoverCard calls the hook, yet a pane importing only the kit fails
        kit_only = "import { Panel, TickerLink } from '@/components/terminal'\nexport function X() { return <Panel><TickerLink symbol='A'/></Panel> }"
        probe = ROOT / "ui" / "components" / "__kit_only_probe__.tsx"
        assert not uses_hook(probe, {**sources, probe: kit_only}), "a pane that only imports the shared kit passed S3"

    def test_periodic_and_eod_only_files_never_claim_live(self, inventory: list[Pane], sources: dict[Path, str]):
        """A file whose every inventory row is periodic / eod-only never builds a LIVE chip (object literal or sourceOf
        live:true); the stored 15-min IV pilot was the case caught (IvLivePath)."""
        live_rows = {f for r in inventory if r.live_capable in ("yes-breeze", "yes-nse-api") for f in r.ui_files}
        quiet = {f for r in inventory if r.live_capable in ("periodic", "eod-only") for f in r.ui_files} - live_rows
        quiet |= {"ui/components/vol/IvLivePath.tsx"}
        bad = {}
        for f in sorted(quiet):
            src = sources.get(ROOT / f, "")
            n = live_literals(src) + len(re.findall(r"\bsourceOf\([^)]*\blive:\s*true", src))
            if n:
                bad[f] = n
        assert not bad, f"periodic / EOD panes claiming LIVE: {bad}"
        assert live_literals("return { state: 'live', source: src, asOf: lastTs }") == 1      # negative control

    def test_the_hover_card_is_live_and_says_its_source(self):
        """The owner's complaint (5 Nov 10:10): the card reads the live hook and prints the row's own source + time line.
        A legacy-route fallback is allowed only behind the hook's missing/error status — and that route answers '.NS'
        from the live service too (B-API), so it can never put a Yahoo price on an NSE name."""
        src = ts_code(UI / "components" / "terminal" / "index.tsx")
        start = src.find("function HoverCard")
        assert start >= 0, "HoverCard not found"
        end = src.find("\nfunction ", start + 10)
        hover = src[start:end if end > 0 else len(src)]
        assert "Yahoo · ≈1 min delayed" not in src, "the hover card still claims Yahoo as its source"
        assert re.search(r"\buseLiveQuotes\s*\(", hover) and "useLiveQuotes" in "".join(hook_locals(src)), \
            "the hover card does not read ui/lib/liveQuotes"
        assert re.search(r"\blineFor\s*\(|\bsourceFor\s*\(", hover), "the hover card prints no source/time line"
        for m in re.finditer(r"\bhoverFallback\s*\(|getNewsQuotes\s*\(", hover):
            ctx = hover[max(0, m.start() - 400):m.start()]
            assert re.search(r"needFallback|status\s*===\s*'missing'", ctx), "a Yahoo-route read outside the fallback guard"

    def test_no_ui_code_calls_a_yahoo_api_host(self, sources: dict[Path, str]):
        """The browser never fetches Yahoo's API hosts (a link-out to finance.yahoo.com/quote is a link, not data)."""
        bad = [str(p.relative_to(ROOT)) for p, s in sources.items() if YAHOO_API_HOST.search(s)]
        assert not bad, bad


class TestNseWebsiteNeverLiveS4:
    def test_no_new_nse_website_live_chip(self, sources: dict[Path, str]):
        now = {str(p.relative_to(ROOT)): nse_live_sites(s) for p, s in sources.items()}
        now = {k: v for k, v in now.items() if v}
        grown = {k: v for k, v in now.items() if v > NSE_LIVE_KNOWN.get(k, 0)}
        assert not grown, f"new NSE-website chips that can read LIVE (NSE web data is 34-172 s old: DELAYED <age>): {grown}"

    def test_the_ratchet_tightens(self, sources: dict[Path, str]):
        now = {str(p.relative_to(ROOT)): nse_live_sites(s) for p, s in sources.items()}
        loose = {k: (v, now.get(k, 0)) for k, v in NSE_LIVE_KNOWN.items() if now.get(k, 0) < v}
        assert not loose, f"fixed — lower NSE_LIVE_KNOWN to the new count: {loose}"


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# B-TICKS — live_ticks.py on recorded ticks (fake Breeze client; no socket, no thread: the worker is driven by _step())
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Ticks recorded by the L-CAPACITY ladder (one Breeze socket, 5 Nov 2026 10:20-10:34 IST; public market data). HDFCBANK
# is the equity shape with its own token. Indices carry '' for bid / ask / ttq.
RECORDED_TICKS: list[dict[str, Any]] = [
    {"symbol": "4.1!NIFTY 50", "open": "24378.05", "last": "24389.5", "high": "24442.2", "low": "24296.3", "change": "1.79",
     "bPrice": "", "bQty": "", "sPrice": "", "sQty": "", "ltq": "", "avgPrice": "", "quotes": "Quotes Data", "ttq": "",
     "totalBuyQt": "", "totalSellQ": "", "ttv": "", "trend": "-", "lowerCktLm": "", "upperCktLm": "",
     "ltt": "Thu Nov  5 10:20:52 2026", "close": "23960.6", "exchange": "NSE Equity", "stock_name": "NIFTY 50"},
    {"symbol": "4.1!NIFTY BANK", "open": "57102.8", "last": "57107.1", "high": "57139.7", "low": "56718.2", "change": "2.13",
     "bPrice": "", "bQty": "", "sPrice": "", "sQty": "", "ltq": "", "avgPrice": "", "quotes": "Quotes Data", "ttq": "",
     "totalBuyQt": "", "totalSellQ": "", "ttv": "", "trend": "+", "lowerCktLm": "", "upperCktLm": "",
     "ltt": "Thu Nov  5 10:34:00 2026", "close": "55913.6", "exchange": "NSE Equity", "stock_name": "NIFTY BANK"},
    {"symbol": "4.1!3499", "open": "182.29", "last": "180.57", "high": "182.66", "low": "180.3", "change": "0.36",
     "bPrice": "180.56", "bQty": "268", "sPrice": "180.63", "sQty": "735", "ltq": "1", "avgPrice": "181.62",
     "quotes": "Quotes Data", "ttq": "8712469", "totalBuyQt": "1358595", "totalSellQ": "2881947", "ttv": "15823.59C",
     "trend": "+", "lowerCktLm": "161.94", "upperCktLm": "197.92", "ltt": "Thu Nov  5 10:21:55 2026", "close": "179.93",
     "exchange": "NSE Equity", "stock_name": "TATA STEEL LIMITED"},
    {"symbol": "4.1!4963", "open": "1458", "last": "1466.9", "high": "1467.8", "low": "1445.9", "change": "3.01",
     "bPrice": "1466.5", "bQty": "482", "sPrice": "1466.9", "sQty": "1063", "ltq": "1", "avgPrice": "1458.56",
     "quotes": "Quotes Data", "ttq": "8463254", "totalBuyQt": "502204", "totalSellQ": "747445", "ttv": "123441.64C",
     "trend": "+", "lowerCktLm": "1281.7", "upperCktLm": "1566.5", "ltt": "Thu Nov  5 10:34:08 2026", "close": "1424.1",
     "exchange": "NSE Equity", "stock_name": "ICICI BANK LIMITED"},
    {"symbol": "4.1!1333", "open": "990.1", "last": "995.25", "high": "998.0", "low": "988.0", "change": "0.81",
     "bPrice": "995.2", "bQty": "120", "sPrice": "995.3", "sQty": "300", "ltq": "5", "avgPrice": "993.4",
     "quotes": "Quotes Data", "ttq": "4100000", "totalBuyQt": "1", "totalSellQ": "1", "ttv": "40729.4C", "trend": "+",
     "lowerCktLm": "891.0", "upperCktLm": "1089.0", "ltt": "Thu Nov  5 10:22:01 2026", "close": "987.25",
     "exchange": "NSE Equity", "stock_name": "HDFC BANK LIMITED"},
]
RECORDED_SYMBOLS = {"4.1!NIFTY 50": "NIFTY 50", "4.1!NIFTY BANK": "NIFTY BANK", "4.1!3499": "TATASTEEL",
                    "4.1!4963": "ICICIBANK", "4.1!1333": "HDFCBANK"}
# The matching rows of ICICI's NSEScripMaster.txt (public; L-CAPACITY scratch copy): HDFCBANK's W3 warrant row is the
# reason get_names returns '1333 1462 17320'; index rows have Series '0' and the name as Token.
MASTER_ROWS = """\
"1333","HDFBAN","EQ","HDFC BANK LIMITED",0.01,1,"","",0,1,"INE040A01034",1017.5,669.2,1020.5,1.2,"","","",0,0,0,798.05,652.95,"",0,"","","",0,"","","","","","","","","","","","","","","","","","","","","","","0",0,0,0,"","","","","","HDFCBANK"
"17320","HDFWA2","W3","HDFC BANK WARRANT AUG 23",0.01,1,"","",0,2,"INE040A13013",1794,1363.55,995,295,"","","",0,0,0,653.55,534.75,"",0,"","","",0,"","","","","","","","","","","","","","","","","","","","","","","0",0,0,0,"","","","","","HDFCBANK"
"2885","RELIND","EQ","RELIANCE INDUSTRIES",0.01,1,"","",0,10,"INE002A01018",1611.8,1152.2,1611.8,8.19,"","","",0,0,0,1438.6,1177.2,"",0,"","","",0,"","","","","","","","","","","","","","","","","","","","","","","0",0,0,0,"","","","","","RELIANCE"
"3499","TATSTE","EQ","TATA STEEL LIMITED",0.01,1,"","",0,1,"INE081A01020",224.4,160.06,224.4,3.71,"","","",0,0,0,194.15,158.85,"",0,"","","",0,"","","","","","","","","","","","","","","","","","","","","","","0",0,0,0,"","","","","","TATASTEEL"
"4963","ICIBAN","EQ","ICICI BANK LIMITED",0.01,1,"","",0,2,"INE090A01021",1480,1187.6,1500,3.77,"","","",0,0,0,1566.9,1282.1,"",0,"","","",0,"","","","","","","","","","","","","","","","","","","","","","","0",0,0,0,"","","","","","ICICIBANK"
"INDIA VIX","INDVIX","0","INDIA VIX VOLATALITY INDEX",0.01,1,"","",0,0,"",2890.75,872,0,0,"","","",0,0,0,0,0,"",0,"","","",0,"","","","","","","","","","","","","","","","","","","","","","","0",0,0,0,"","","","","","INDVIX"
"NIFTY 50","NIFTY","0","NIFTY 50",0.01,1,"","",0,0,"",26373.2,22179.9,0,0,"","","",0,0,0,0,0,"",0,"","","",0,"","","","","","","","","","","","","","","","","","","","","","","0",0,0,0,"","","","","","NIFTY 50"
"NIFTY BANK","CNXBAN","0","NIFTY BANK",0.01,1,"","",0,0,"",61764.85,49954.85,0,0,"","","",0,0,0,0,0,"",0,"","","",0,"","","","","","","","","","","","","","","","","","","","","","","0",0,0,0,"","","","","","NIFTY BANK"
"""


def _data_service_path() -> None:
    for p in (str(ROOT), str(DATA_SVC)):
        if p not in sys.path:
            sys.path.insert(0, p)


@pytest.fixture(scope="module")
def lt() -> Any:
    _data_service_path()
    import live_ticks

    return live_ticks


@pytest.fixture(scope="module")
def provider_mod() -> Any:
    _data_service_path()
    from providers import icici_breeze_provider

    return icici_breeze_provider


class FakeBreeze:
    """The BreezeConnect surface live_ticks uses; records subscriptions; never a socket."""

    def __init__(self, names: dict[str, dict[str, str]] | None = None):
        self.on_ticks: Any = None
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.connects = 0
        self.names = names or {}
        self.rest_calls: list[str] = []

    def ws_connect(self) -> None:
        self.connects += 1

    def ws_disconnect(self) -> None:
        pass

    def subscribe_feeds(self, **kw: Any) -> dict[str, str]:
        toks = kw.get("stock_token") or kw.get("stock_code")
        self.subscribed.extend(toks if isinstance(toks, list) else [str(toks)])
        return {"message": "subscribed (fake)"}

    def unsubscribe_feeds(self, **kw: Any) -> dict[str, str]:
        toks = kw.get("stock_token") or kw.get("stock_code")
        self.unsubscribed.extend(toks if isinstance(toks, list) else [str(toks)])
        return {"message": "unsubscribed (fake)"}

    def get_names(self, exchange_code: str, stock_code: str) -> dict[str, str]:
        return self.names.get(stock_code, {})

    def get_quotes(self, **kw: Any) -> None:            # the REST quota: the live path must never call it
        self.rest_calls.append("get_quotes")
        raise AssertionError("Breeze REST get_quotes on the tick path")


class FakeProvider:
    """``_resolve_ws_token`` is the REAL provider method, run over the fixture master (or an empty one)."""

    def __init__(self, provider_mod: Any, breeze: FakeBreeze, master: str = MASTER_ROWS):
        import csv
        import io

        self._breeze = breeze
        self._maps = provider_mod.parse_nse_master_tokens(csv.reader(io.StringIO(master)))
        self._real = provider_mod.ICICIBreezeProvider._resolve_ws_token

    def is_connected(self) -> bool:
        return True

    def ws_token_maps(self) -> tuple[dict[str, str], dict[str, str]]:
        return self._maps

    def _resolve_ws_token(self, ticker: str) -> str:
        return self._real(self, ticker)

    def _resolve_isec_code(self, sym: str) -> str:      # the legacy (pre-fix) path, for the negative control
        return {"HDFCBANK": "HDFBAN", "TATASTEEL": "TATSTE", "ICICIBANK": "ICIBAN"}.get(sym, sym)


def _engine(lt: Any, prov: Any, clock: list[float], *, holdings: Iterable[str] = (), pins: Iterable[str] = (),
            hours: bool = True) -> Any:
    flag = [False]                                      # ensure() never starts the worker thread in a test
    obj = lt.LiveTicks(lambda: prov, prev_close_fn=lambda syms: {}, holdings_fn=lambda: list(holdings),
                       clock=lambda: clock[0], enabled_fn=lambda: flag[0], market_hours_fn=lambda: hours,
                       pins_fn=lambda: list(pins))
    return obj


def old_isec_key(payload: dict[str, Any], isec_to_sym: dict[str, str]) -> str:
    """The pre-fix lookup (live_ticks.py before 5 Nov 2026): the first of stock_code / symbol / stock_name, mapped
    through the isec codes given to subscribe_feeds, else kept raw."""
    raw = next((payload[k] for k in ("stock_code", "symbol", "stock_name") if payload.get(k) not in (None, "")), "")
    return isec_to_sym.get(str(raw).upper(), str(raw).upper())


class TestTickEngineBTicks:
    @pytest.fixture(autouse=True)
    def _no_tick_persistence(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A tick fed to the engine would reach tick_store (parquet under data/ticks): never from a test."""
        monkeypatch.setenv("TICK_PERSIST", "0")
        monkeypatch.setenv("TICKS_DIR", str(tmp_path / "ticks"))

    def test_negative_control_the_old_isec_lookup_files_every_recorded_tick_under_a_raw_key(self):
        isec = {"HDFBAN": "HDFCBANK", "TATSTE": "TATASTEEL", "ICIBAN": "ICICIBANK", "NIFTY": "NIFTY 50"}
        keys = [old_isec_key(t, isec) for t in RECORDED_TICKS]
        assert keys == [t["symbol"] for t in RECORDED_TICKS] and all(k.startswith("4.1!") for k in keys)
        assert not set(keys) & set(RECORDED_SYMBOLS.values()), "the old scheme found a symbol: the control is wrong"

    def test_recorded_ticks_map_to_nse_symbols_and_index_names(self, lt: Any, provider_mod: Any):
        clock = [1_000.0]
        breeze = FakeBreeze()
        prov = FakeProvider(provider_mod, breeze)
        eng = _engine(lt, prov, clock)
        eng.ensure(["HDFCBANK", "TATASTEEL.NS", "ICICIBANK", "NIFTY 50", "NIFTY BANK"])
        assert eng._step() is True and breeze.connects == 1
        assert set(breeze.subscribed) == set(RECORDED_SYMBOLS), breeze.subscribed        # tokens, never isec codes
        for t in RECORDED_TICKS:
            breeze.on_ticks(dict(t))                       # the callback the engine registered on the client
        snap = eng.snapshot()
        assert set(snap) == set(RECORDED_SYMBOLS.values()), sorted(snap)
        ts = snap["TATASTEEL"]
        assert ts["price"] == 180.57 and ts["prev_close"] == 179.93 and ts["bid"] == 180.56 and ts["ask"] == 180.63
        assert ts["chg_pct"] == pytest.approx((180.57 / 179.93 - 1) * 100, abs=1e-3)
        nifty = snap["NIFTY 50"]
        assert nifty["price"] == 24389.5 and nifty["prev_close"] == 23960.6
        assert nifty["bid"] is None and nifty["ask"] is None                              # '' on index ticks
        assert eng.status()["state"] in ("LIVE", "OFF") and not breeze.rest_calls

    def test_an_unsubscribed_token_is_counted_never_stored_under_its_raw_key(self, lt: Any, provider_mod: Any):
        clock = [1_000.0]
        breeze = FakeBreeze()
        eng = _engine(lt, FakeProvider(provider_mod, breeze), clock)
        eng.ensure(["TATASTEEL"])
        eng._step()
        breeze.on_ticks({**RECORDED_TICKS[3]})             # ICICIBANK's token: not subscribed here
        snap = eng.snapshot()
        assert snap == {} and not any(k.startswith("4.1!") for k in snap)
        assert eng.status().get("unmapped_ticks", 0) >= 1

    def test_get_names_fallback_takes_the_first_isec_token_of_the_same_company(self, provider_mod: Any):
        names = {"HDFCBANK": {"isec_token_level1": "4.1!1333 1462 17320", "exchange_stock_code": "HDFCBANK"},
                 "WRONGCO": {"isec_token_level1": "4.1!555", "exchange_stock_code": "OTHERCO"}}
        prov = FakeProvider(provider_mod, FakeBreeze(names), master="")
        assert prov._resolve_ws_token("HDFCBANK") == "4.1!1333"
        with pytest.raises(LookupError):
            prov._resolve_ws_token("WRONGCO")              # get_names matched another company's short name
        with pytest.raises(LookupError):
            prov._resolve_ws_token("NOSUCH")

    def test_master_tokens_prefer_the_eq_row_and_keep_index_names(self, provider_mod: Any):
        import csv
        import io

        eq, idx = provider_mod.parse_nse_master_tokens(csv.reader(io.StringIO(MASTER_ROWS)))
        assert eq["HDFCBANK"] == "1333" and eq["TATASTEEL"] == "3499" and eq["ICICIBANK"] == "4963" and eq["RELIANCE"] == "2885"
        assert "17320" not in eq.values()                  # the W3 warrant row is not the cash stream
        assert {"NIFTY 50", "NIFTY BANK", "INDIA VIX"} <= set(idx)

    def test_cap_is_the_contract_range(self, lt: Any):
        assert CAP_MIN <= lt.MAX_SYMBOLS <= CAP_MAX, lt.MAX_SYMBOLS

    def test_pins_first_never_evicted_ttl_drops_requests_and_overflow_drops_the_oldest(self, lt: Any, provider_mod: Any):
        clock = [10_000.0]
        pins = ["NIFTY 50", "NIFTY BANK"] + [f"PIN{i:02d}" for i in range(60)]
        eng = _engine(lt, FakeProvider(provider_mod, FakeBreeze()), clock, holdings=["HOLD1"], pins=pins)
        n_req = lt.MAX_SYMBOLS + 40
        for i in range(n_req):                              # one request per second, oldest first
            clock[0] += 1
            eng.ensure([f"R{i:03d}"])
        target = eng._target_set()
        assert len(target) == lt.MAX_SYMBOLS
        assert target[0] == "HOLD1" and set(pins) <= set(target)                       # pins never pushed out
        room = lt.MAX_SYMBOLS - 1 - len(pins)
        kept = [s for s in target if s.startswith("R")]
        assert kept == [f"R{i:03d}" for i in range(n_req - 1, n_req - 1 - room, -1)]   # most recent first
        clock[0] += lt.SYMBOL_TTL_S + 1                                                # every request ages out …
        after = eng._target_set()
        assert after == ["HOLD1"] + pins                                               # … the pins stay
        assert len(eng._requested) == 0

    def test_requested_ledger_is_bounded_while_the_switch_is_off(self, lt: Any, provider_mod: Any):
        clock = [10_000.0]
        eng = _engine(lt, FakeProvider(provider_mod, FakeBreeze()), clock)
        for i in range(lt.REQUESTED_CAP + 200):
            clock[0] += 0.01
            eng.ensure([f"Q{i:04d}"])
        assert len(eng._requested) <= lt.REQUESTED_CAP and eng.state == "OFF" and eng._thread is None

    def test_kill_switch_default_off(self, lt: Any, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("LIVE_TICKS", raising=False)
        assert lt.enabled() is False
        monkeypatch.setenv("LIVE_TICKS", "1")
        assert lt.enabled() is True

    def test_status_carries_the_contract_engine_fields(self, lt: Any, provider_mod: Any):
        eng = _engine(lt, FakeProvider(provider_mod, FakeBreeze()), [1_000.0])
        st = eng.status()
        assert {"state", "subscribed", "ticks_per_min", "last_tick_age_s", "cap"} <= set(st), sorted(st)
        assert st["state"] in FEED_STATES and st["cap"] == lt.MAX_SYMBOLS


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# B-QUOTES — data-service live_quotes.LiveQuotes on fakes: the real LiveTicks (fake Breeze), a fake NSE client (the
# NseLive surface the poller uses), a fake EOD reader; the clock is IST wall time on 5-7 Nov 2026
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
def ist(day: int, h: int, m: int, sec: int = 0) -> float:
    from datetime import datetime, timedelta, timezone

    return datetime(2026, 11, day, h, m, sec, tzinfo=timezone(timedelta(hours=5, minutes=30))).timestamp()


def nse_stamp(epoch: float, seconds: bool = True) -> str:
    from datetime import datetime, timedelta, timezone

    t = datetime.fromtimestamp(epoch, tz=timezone(timedelta(hours=5, minutes=30)))
    return t.strftime("%d-%b-%Y %H:%M:%S" if seconds else "%d-%b-%Y %H:%M")


class FakeNse:
    """The NseLive surface live_quotes' poller uses (get / cached_at / heatmap_lists / blocked_until); never a socket."""

    def __init__(self, clock: list[float]):
        self.clock = clock
        self.payloads: dict[str, Any] = {}
        self.fetched: dict[str, float] = {}
        self.calls: list[str] = []
        self.blocked_until = 0.0

    def heatmap_lists(self) -> list[tuple[str, str]]:
        return [("Broad Market Indices", "NIFTY 50")]

    def cached_at(self, path: str) -> float | None:
        return self.fetched.get(path)

    def get(self, path: str, ttl_open: float = 30, ttl_closed: float = 300) -> Any:
        at = self.fetched.get(path)
        if at is None or self.clock[0] - at >= ttl_open:
            self.calls.append(path)
            self.fetched[path] = self.clock[0]
        for key, val in self.payloads.items():
            if path.startswith(key):
                return val
        return [] if path.startswith("heatmap") else {}


def heatmap_row(sym: str, last: float, chg: float, stamp: float) -> dict[str, Any]:
    return {"symbol": sym, "series": "EQ", "lastPrice": last, "change": chg, "pChange": round(chg / (last - chg) * 100, 2),
            "high": last + 5, "low": last - 5, "VWAP": last, "totalTradedVolume": 1000, "quantityTraded": 1.0e8,
            "lastUpdatedTime": nse_stamp(stamp)}


class Harness:
    """LiveQuotes + LiveTicks wired the way data-service main.py wires them, on fakes."""

    def __init__(self, lt: Any, lq: Any, provider_mod: Any, now: float, *, eod: dict[str, dict] | None = None,
                 holdings: Iterable[str] = (), watchlist: Iterable[str] = (), members: dict[str, list[str]] | None = None,
                 armed: bool = True):
        self.clock = [now]
        self.breeze = FakeBreeze()
        self.prov = FakeProvider(provider_mod, self.breeze)
        self.nse = FakeNse(self.clock)
        self.eod = dict(eod or {})
        self.eod_calls: list[list[str]] = []
        self.ticks = lt.LiveTicks(lambda: self.prov, prev_close_fn=lambda syms: {}, holdings_fn=lambda: list(holdings),
                                  clock=lambda: self.clock[0], enabled_fn=lambda: armed, market_hours_fn=lambda: True,
                                  pins_fn=lambda: list(self.quotes.pinned_symbols()))
        self.ticks._kick = lambda resync=True: None     # armed, but the worker is driven by _step() here (no thread)

        def eod_fn(syms: list[str]) -> dict[str, dict]:
            self.eod_calls.append(list(syms))
            return {x: self.eod[x] for x in syms if x in self.eod}

        self.quotes: Any = lq.LiveQuotes(ticks_getter=lambda: self.ticks, nse_getter=lambda: self.nse, eod_fn=eod_fn,
                                    session_fn=lambda: True, holdings_fn=lambda: list(holdings),
                                    watchlist_fn=lambda: list(watchlist),
                                    members_fn=lambda ix: list((members or {}).get(ix, [])),
                                    holidays_fn=lambda: set(), clock=lambda: self.clock[0], sleep_fn=lambda _s: None,
                                    start_poller=False)

    def subscribe(self, *syms: str) -> None:
        self.ticks.ensure(list(syms))
        self.ticks._step()                              # connect + subscribe on the fake client (no thread)

    def tick(self, payload: dict[str, Any], **override: Any) -> None:
        self.breeze.on_ticks({**payload, **override})

    def at(self, epoch: float) -> None:
        self.clock[0] = epoch

    def get(self, *syms: str) -> dict[str, Any]:
        return self.quotes.quotes(list(syms))


TATA = RECORDED_TICKS[2]
NIFTY = RECORDED_TICKS[0]
EOD_ROWS = {"INFY": {"date": "2026-11-04", "close": 1500.0, "prev_close": 1490.0, "open": 1491, "high": 1510, "low": 1488,
                     "volume": 1, "value_cr": 1.0, "table": "nse_bhavcopy"},
            "TATASTEEL": {"date": "2026-11-04", "close": 179.93, "prev_close": 178.0, "open": 178, "high": 181, "low": 177,
                          "volume": 1, "value_cr": 1.0, "table": "nse_bhavcopy"}}


@pytest.fixture(scope="module")
def lq() -> Any:
    _data_service_path()
    need(DATA_SVC / "live_quotes.py", "LV-DATA")
    import live_quotes

    return live_quotes


@pytest.fixture(autouse=True)
def _ist_process_clock(monkeypatch: pytest.MonkeyPatch) -> Iterable[None]:
    """Breeze formats ltt in PROCESS-LOCAL time (the SDK's strftime('%c')) and live_ticks inverts it with time.mktime;
    the recorded ticks are IST, so the gates run in IST whatever the CI machine's zone."""
    import time as _time

    monkeypatch.setenv("TZ", "Asia/Kolkata")
    _time.tzset()
    yield
    monkeypatch.undo()
    _time.tzset()


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Every socket connect in this test fails loudly (and is recorded): the request path is memory + fakes only."""
    import socket

    tried: list[Any] = []

    def refuse(self: Any, addr: Any) -> None:
        tried.append(addr)
        raise OSError("live-gates: network refused")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setenv("TICK_PERSIST", "0")
    return tried


def assert_contract_row(sym: str, q: dict[str, Any]) -> None:
    assert QUOTE_KEYS <= set(q), (sym, sorted(QUOTE_KEYS - set(q)))
    assert q["state"] in STATES, (sym, q["state"])
    assert q["source"] in SOURCES or (q["state"] == "unavailable" and q["source"] is None), (sym, q["source"])
    if q["state"] == "live":                            # live is a Breeze tick, never NSE's website or a close
        assert q["source"] == "breeze_ws", (sym, q)
        assert q["age_s"] is not None and (q["age_s"] <= LIVE_FRESH_S or "quiet" in str(q.get("reason") or "")), (sym, q)
        assert q["age_s"] <= 120.0, (sym, q)
    if q["source"] == "nse_api":
        assert q["state"] in ("delayed", "stale", "closed"), (sym, q)
        assert q["state"] != "delayed" or q["age_s"] <= NSE_DELAYED_MAX_S, (sym, q)
    if q["ltt"]:
        assert str(q["ltt"]).endswith("+05:30"), (sym, q["ltt"])


class TestLiveQuotesBQuotes:
    def test_fresh_tick_is_live_breeze(self, lt: Any, lq: Any, provider_mod: Any, no_network: list[Any]):
        h = Harness(lt, lq, provider_mod, ist(5, 10, 21, 56), eod=EOD_ROWS)
        h.subscribe("TATASTEEL")
        h.tick(TATA)
        h.at(ist(5, 10, 21, 58))
        body = h.get("TATASTEEL")
        assert body["market"] == {"state": "open", "session_date": "2026-11-05"}
        q = body["quotes"]["TATASTEEL"]
        assert_contract_row("TATASTEEL", q)
        assert (q["state"], q["source"], q["price"], q["prev_close"]) == ("live", "breeze_ws", 180.57, 179.93)
        assert q["age_s"] == pytest.approx(2.0, abs=0.2) and q["ltt"] == "2026-11-05T10:21:55+05:30"
        assert q["bid"] == 180.56 and q["ask"] == 180.63 and q["day_high"] == 182.66
        assert not no_network and not h.breeze.rest_calls

    def test_old_tick_without_a_healthy_feed_is_not_live(self, lt: Any, lq: Any, provider_mod: Any, no_network: list[Any]):
        h = Harness(lt, lq, provider_mod, ist(5, 10, 21, 56), eod=EOD_ROWS)
        h.subscribe("TATASTEEL")
        h.tick(TATA)
        h.at(ist(5, 10, 22, 26))                         # 30 s, nothing else ticked: the socket is not healthy
        q = h.get("TATASTEEL")["quotes"]["TATASTEEL"]
        assert_contract_row("TATASTEEL", q)
        assert q["state"] == "delayed" and q["source"] == "breeze_ws" and q["age_s"] == pytest.approx(30, abs=0.5)
        h.at(ist(5, 10, 24, 0))                          # 124 s: older than the delayed window
        q2 = h.get("TATASTEEL")["quotes"]["TATASTEEL"]
        assert_contract_row("TATASTEEL", q2)
        assert q2["state"] == "stale", q2

    def test_quiet_name_on_a_healthy_feed_says_why_and_never_past_120_s(self, lt: Any, lq: Any, provider_mod: Any,
                                                                         no_network: list[Any]):
        h = Harness(lt, lq, provider_mod, ist(5, 10, 21, 56), eod=EOD_ROWS)
        h.subscribe("TATASTEEL", "NIFTY 50")
        h.tick(TATA)
        for sec in range(0, 61, 5):                     # NIFTY 50 keeps the socket's heartbeat (10 Hz in reality)
            h.at(ist(5, 10, 21, 56) + sec)
            h.tick(NIFTY)
        q = h.get("TATASTEEL")["quotes"]["TATASTEEL"]
        assert_contract_row("TATASTEEL", q)
        assert q["age_s"] == pytest.approx(60, abs=0.5)
        if q["state"] == "live":                          # LV-DATA's quiet-name rule (a contract deviation: see notes)
            assert "quiet" in (q.get("reason") or ""), q
        else:
            assert q["state"] == "delayed", q
        # negative control: the same 60 s tick with the kill switch OFF (no healthy socket) is never live
        off = Harness(lt, lq, provider_mod, ist(5, 10, 21, 56), eod=EOD_ROWS, armed=False)
        off.subscribe("TATASTEEL", "NIFTY 50")
        off.tick(TATA)
        for sec in range(0, 61, 5):
            off.at(ist(5, 10, 21, 56) + sec)
            off.tick(NIFTY)
        assert off.get("TATASTEEL")["quotes"]["TATASTEEL"]["state"] == "delayed"
        for sec in range(61, 200, 5):
            h.at(ist(5, 10, 21, 56) + sec)
            h.tick(NIFTY)
        q2 = h.get("TATASTEEL")["quotes"]["TATASTEEL"]
        assert q2["state"] != "live" and q2["age_s"] > 120, q2
        assert h.get("NIFTY 50")["quotes"]["NIFTY 50"]["state"] == "live"

    def test_nse_website_is_delayed_then_stale_never_live(self, lt: Any, lq: Any, provider_mod: Any,
                                                          no_network: list[Any]):
        now = ist(5, 11, 0, 0)
        h = Harness(lt, lq, provider_mod, now, eod=EOD_ROWS)
        h.nse.payloads["heatmap-symbols"] = [heatmap_row("TCS", 3100.0, 10.0, now - 40)]
        h.nse.payloads["allIndices"] = {"timestamp": nse_stamp(now - 60, seconds=False), "data": [
            {"index": "NIFTY 50", "last": 24400.0, "variation": 439.4, "percentChange": 1.83, "previousClose": 23960.6,
             "open": 24378.05, "high": 24442.2, "low": 24296.3}]}
        h.get("TCS", "NIFTY 50")                         # demand for the poller
        did = h.quotes.poll_nse_once()
        assert "error" not in did, did
        body = h.get("TCS", "NIFTY 50")
        tcs, nifty = body["quotes"]["TCS"], body["quotes"]["NIFTY 50"]
        for sym, q in (("TCS", tcs), ("NIFTY 50", nifty)):
            assert_contract_row(sym, q)
            assert q["source"] == "nse_api" and q["state"] == "delayed", (sym, q)
        assert tcs["price"] == 3100.0 and tcs["age_s"] >= 40 and tcs["prev_close"] == 3090.0
        assert nifty["price"] == 24400.0 and nifty["age_s"] >= 1                      # a minute label is never "now"
        h.at(now + 70)                                    # TCS's NSE copy is now 110 s old
        q = h.get("TCS")["quotes"]["TCS"]
        assert_contract_row("TCS", q)
        assert q["source"] == "nse_api" and q["state"] == "stale", q
        assert not no_network and all(not c.startswith(("quote-equity", "http")) for c in h.nse.calls)

    def test_nse_poller_paces_itself(self, lt: Any, lq: Any, provider_mod: Any, no_network: list[Any]):
        now = ist(5, 11, 0, 0)
        h = Harness(lt, lq, provider_mod, now, eod=EOD_ROWS)
        h.nse.payloads["heatmap-symbols"] = [heatmap_row("TCS", 3100.0, 10.0, now - 20)]
        h.get("TCS", "NIFTY 50")
        h.quotes.poll_nse_once()
        first = list(h.nse.calls)
        assert "allIndices" in first and any(c.startswith("heatmap-symbols") for c in first), first
        for i in range(1, 15):                            # the thread would run every 2 s for 28 s
            h.at(now + 2 * i)
            h.quotes.poll_nse_once()
        again = h.nse.calls[len(first):]
        assert not [c for c in again if c.startswith("heatmap-symbols")], f"a heatmap list re-fetched inside 60 s: {again}"
        assert sum(c == "allIndices" for c in h.nse.calls) <= 2, h.nse.calls          # ≥ 15 s apart over 28 s

    def test_eod_close_is_stale_during_the_session_and_unavailable_without_one(self, lt: Any, lq: Any,
                                                                                 provider_mod: Any, no_network: list[Any]):
        h = Harness(lt, lq, provider_mod, ist(5, 11, 0, 0), eod=EOD_ROWS)
        body = h.get("INFY", "NOSUCH")
        q, u = body["quotes"]["INFY"], body["quotes"]["NOSUCH"]
        assert_contract_row("INFY", q)
        assert (q["source"], q["state"], q["price"]) == ("eod", "stale", 1500.0) and q.get("reason"), q
        assert_contract_row("NOSUCH", u)
        assert u["state"] == "unavailable" and u["price"] is None and u.get("reason"), u

    def test_after_1530_the_last_price_reads_closed_with_the_session_date(self, lt: Any, lq: Any, provider_mod: Any,
                                                                            no_network: list[Any]):
        h = Harness(lt, lq, provider_mod, ist(5, 15, 29, 58), eod=EOD_ROWS)
        h.subscribe("TATASTEEL")
        h.tick(TATA, ltt="Thu Nov  5 15:29:57 2026", last="181.10")
        assert h.get("TATASTEEL")["quotes"]["TATASTEEL"]["state"] == "live"
        h.at(ist(5, 15, 45, 0))
        body = h.get("TATASTEEL", "INFY")
        assert body["market"] == {"state": "closed", "session_date": "2026-11-05"}
        t, i = body["quotes"]["TATASTEEL"], body["quotes"]["INFY"]
        for sym, q in (("TATASTEEL", t), ("INFY", i)):
            assert_contract_row(sym, q)
        assert t["state"] == "closed" and t["price"] == 181.10 and t["source"] == "breeze_ws", t      # today's last trade
        assert i["state"] == "stale" and "2026-11-04" in (i.get("reason") or ""), i    # yesterday's close is not CLOSE
        h.eod["TATASTEEL"] = {**EOD_ROWS["TATASTEEL"], "date": "2026-11-05", "close": 181.0}
        h.eod["INFY"] = {**EOD_ROWS["INFY"], "date": "2026-11-05", "close": 1510.0}
        h.at(ist(5, 19, 0, 0) + lq.EOD_TTL_S)            # the 18:30 bhavcopy is stored; the EOD cache has expired
        body2 = h.get("TATASTEEL", "INFY")
        assert [body2["quotes"][x]["state"] for x in ("TATASTEEL", "INFY")] == ["closed", "closed"]
        assert body2["quotes"]["INFY"]["source"] == "eod" and body2["quotes"]["INFY"]["price"] == 1510.0

    def test_weekend_and_pre_open_market_states(self, lt: Any, lq: Any, provider_mod: Any, no_network: list[Any]):
        sat = Harness(lt, lq, provider_mod, ist(7, 11, 0, 0), eod={"INFY": {**EOD_ROWS["INFY"], "date": "2026-11-06"}})
        body = sat.get("INFY")
        assert body["market"] == {"state": "closed", "session_date": "2026-11-06"}
        assert body["quotes"]["INFY"]["state"] == "closed"
        pre = Harness(lt, lq, provider_mod, ist(5, 9, 5, 0), eod=EOD_ROWS)
        b2 = pre.get("INFY")
        assert b2["market"]["state"] == "pre-open" and b2["quotes"]["INFY"]["state"] != "live"

    def test_never_yahoo_and_never_breeze_rest_on_the_request_path(self, lt: Any, lq: Any, provider_mod: Any,
                                                                    no_network: list[Any]):
        h = Harness(lt, lq, provider_mod, ist(5, 11, 0, 0), eod=EOD_ROWS)
        h.subscribe("TATASTEEL")
        for _ in range(3):
            h.get("TATASTEEL", "INFY", "NIFTY 50", "TCS", "RELIANCE")
        assert not no_network and not h.breeze.rest_calls
        assert not h.nse.calls, f"the request path called NSE: {h.nse.calls} (store, then show: poller only)"
        assert len(h.eod_calls) == 1, h.eod_calls                                    # EOD rows cached (≤ 1 read / 10 min)

    def test_request_cap_and_ensure_on_ask(self, lt: Any, lq: Any, provider_mod: Any, no_network: list[Any]):
        h = Harness(lt, lq, provider_mod, ist(5, 11, 0, 0))
        syms = [f"S{i:03d}" for i in range(MAX_REQUEST_SYMBOLS + 50)]
        body = h.get(*syms)
        assert len(body["quotes"]) == MAX_REQUEST_SYMBOLS
        assert len(h.ticks._requested) == MAX_REQUEST_SYMBOLS                         # asking ensured them

    def test_pins_while_open_only_and_they_reach_the_tick_engine(self, lt: Any, lq: Any, provider_mod: Any,
                                                                  no_network: list[Any]):
        members = {"NIFTY 50": ["RELIANCE", "HDFCBANK", "TATASTEEL"], "NIFTY BANK": ["HDFCBANK", "ICICIBANK", "SBIN"]}
        h = Harness(lt, lq, provider_mod, ist(5, 10, 0, 0), holdings=["HOLD1"], watchlist=["WATCH1"], members=members)
        pins = h.quotes.pinned_symbols()
        assert {"NIFTY 50", "NIFTY BANK", "INDIA VIX", "RELIANCE", "HDFCBANK", "TATASTEEL", "ICICIBANK", "SBIN",
                "WATCH1"} <= set(pins), pins
        target = h.ticks._target_set()
        assert set(pins) <= set(target) and "HOLD1" in target
        h.at(ist(5, 20, 0, 0))
        assert h.quotes.pinned_symbols() == [], "pinned outside the session"
        h.at(ist(7, 11, 0, 0))
        assert h.quotes.pinned_symbols() == [], "pinned on a Saturday"

    def test_status_has_the_contract_keys(self, lt: Any, lq: Any, provider_mod: Any, no_network: list[Any]):
        h = Harness(lt, lq, provider_mod, ist(5, 11, 0, 0))
        st = h.quotes.status()
        assert STATUS_KEYS <= set(st), sorted(STATUS_KEYS - set(st))
        assert st["state"] in FEED_STATES and isinstance(st["breeze_session"], bool)
        assert {"ok", "last_ok_at"} <= set(st["nse_fallback"]) and st["cap"] == lt.MAX_SYMBOLS


# the HTTP route on the real data-service app (subprocess: TestClient, no lifespan, sockets refused, the engine swapped
# for one on fakes — no DuckDB, no NSE, no Breeze)
DS_DRIVER = r"""
import importlib.util, json, os, socket, sys
ROOT = __ROOT__
_orig = socket.socket.connect
def _guard(self, addr):
    if self.family == getattr(socket, "AF_UNIX", None):
        return _orig(self, addr)
    raise OSError("live-gates: network refused")
socket.socket.connect = _guard
sys.path[:0] = [ROOT, os.path.join(ROOT, "services", "data-service")]
spec = importlib.util.spec_from_file_location("ds_main_livegates", os.path.join(ROOT, "services", "data-service", "main.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
import live_quotes
NOW = __NOW__
eod = {"INFY": {"date": "2026-11-04", "close": 1500.0, "prev_close": 1490.0, "open": 1491, "high": 1510, "low": 1488,
                "volume": 1, "value_cr": 1.0, "table": "nse_bhavcopy"}}
mod._live_quotes = live_quotes.LiveQuotes(ticks_getter=lambda: None, nse_getter=lambda: None,
                                          eod_fn=lambda syms: {s: eod[s] for s in syms if s in eod},
                                          holidays_fn=lambda: set(), clock=lambda: NOW, start_poller=False)
from fastapi.testclient import TestClient
c = TestClient(mod.app, raise_server_exceptions=False)
h = {"host": "127.0.0.1:8001"}
r1 = c.get("/live/quotes", params={"symbols": "INFY,NIFTY 50"}, headers=h)
r2 = c.get("/live/status", headers=h)
print(__MARK__ + json.dumps({"quotes": [r1.status_code, r1.json()], "status": [r2.status_code, r2.json()]}), flush=True)
"""


def test_data_service_routes_answer_the_contract(tmp_path: Path):
    need(DATA_SVC / "live_quotes.py", "LV-DATA")
    code = (DS_DRIVER.replace("__ROOT__", repr(str(ROOT))).replace("__NOW__", repr(ist(5, 11, 0, 0)))
            .replace("__MARK__", repr(API_MARK)))
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "LIVE_TICKS": "0", "TICK_PERSIST": "0",
           "TICKS_DIR": str(tmp_path / "ticks"), "BREEZE_BUDGET_DB": str(tmp_path / "breeze_budget.sqlite")}
    p = subprocess.run([P, "-c", code], capture_output=True, text=True, timeout=240, env=env, cwd=str(tmp_path))
    line = next((ln for ln in reversed(p.stdout.splitlines()) if ln.startswith(API_MARK)), None)
    assert line is not None, f"data-service harness: no result (exit {p.returncode}); stderr: {p.stderr[-2000:]}"
    res = json.loads(line[len(API_MARK):])
    (s1, body), (s2, st) = res["quotes"], res["status"]
    assert s1 == 200 and body["market"] == {"state": "open", "session_date": "2026-11-05"}, body
    for sym in ("INFY", "NIFTY 50"):
        assert_contract_row(sym, body["quotes"][sym])
    assert body["quotes"]["INFY"]["state"] == "stale" and body["quotes"]["NIFTY 50"]["state"] == "unavailable"
    assert s2 == 200 and STATUS_KEYS <= set(st) and st["state"] == "OFF", st                  # LIVE_TICKS unset: OFF


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# B-API — ui-api in a hermetic subprocess (TestClient, no lifespan; every socket refused; httpx answered by a fake
# data-service; Yahoo hosts a tripwire that records and answers a minimal chart so the positive control can price)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
API_MARK = "LIVEGATE "

API_DRIVER = r"""
import importlib.util, json, os, socket, sys, time
from urllib.parse import parse_qs
ROOT = __ROOT__
SCENARIOS = __SCENARIOS__

# 1. no packet leaves this process: the live stack listens on 127.0.0.1 and must never be reached from a test
_orig_connect = socket.socket.connect
def _guard(self, addr):
    if self.family == getattr(socket, "AF_UNIX", None):
        return _orig_connect(self, addr)
    raise OSError("live-gates: network refused in the test process")
socket.socket.connect = _guard
socket.socket.connect_ex = lambda self, addr: (_guard(self, addr), 111)[1]
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(OSError("live-gates: network refused"))

import httpx
HITS = {"yahoo": [], "ds": [], "other": []}
MODE = {"ds": "live"}
NOW = time.time()

def _quote(sym):
    q = {"price": 101.5, "change": 1.5, "change_pct": 1.5, "prev_close": 100.0, "open": 100.2, "day_high": 102.0,
         "day_low": 99.8, "volume": 12345, "value_cr": 1.25, "bid": 101.45, "ask": 101.55,
         "ltt": "2026-11-05T11:00:00+05:30", "source": "breeze_ws", "age_s": 0.4, "state": "live"}
    if MODE["ds"] == "nse":
        q.update(source="nse_api", age_s=48.0, state="delayed", bid=None, ask=None)
    return q

def _yahoo_chart(sym):
    ts = [int(NOW) - 86400 * i for i in range(30, 0, -1)]
    closes = [4000.0 + i for i in range(30)]
    return {"chart": {"result": [{"meta": {"symbol": sym, "regularMarketPrice": 4100.0, "regularMarketTime": int(NOW),
                                           "currency": "USD", "gmtoffset": 0},
                                  "timestamp": ts, "indicators": {"quote": [{"open": closes, "high": closes,
                                  "low": closes, "close": closes, "volume": [1] * 30}]}}]}}

def _answer(request):
    url = request.url
    host, path = url.host or "", url.path
    if "yahoo" in host:
        HITS["yahoo"].append(path.rsplit("/", 1)[-1])
        return httpx.Response(200, json=_yahoo_chart(path.rsplit("/", 1)[-1]), request=request)
    if host in ("localhost", "127.0.0.1", "data-service") and (url.port in (8001, None)):
        q = parse_qs(url.query.decode() if isinstance(url.query, bytes) else str(url.query))
        syms = [s for s in ",".join(q.get("symbols", [])).split(",") if s]
        HITS["ds"].append({"path": path, "n": len(syms), "syms": [s for s in syms if s in __ASKED__]})
        if MODE["ds"] == "down":
            raise httpx.ConnectError("data-service down (fake)", request=request)
        if path == "/live/quotes":
            return httpx.Response(200, request=request, json={
                "as_of": "2026-11-05T11:00:00+05:30", "market": {"state": "open", "session_date": "2026-11-05"},
                "quotes": {s.upper().replace(".NS", ""): _quote(s) for s in syms}})
        if path == "/live/status":
            return httpx.Response(200, request=request, json={
                "state": "LIVE", "subscribed": 120, "ticks_per_min": 3400, "last_tick_age_s": 0.1, "cap": 300,
                "breeze_session": True, "nse_fallback": {"ok": True, "last_ok_at": "2026-11-05T10:59:30+05:30"}})
        if path == "/live/ticks":
            return httpx.Response(200, request=request, json={"state": "OFF", "connected": False, "ticks": {}})
        if path == "/db/prev-close":
            return httpx.Response(200, request=request, json={"prev": {}})
        return httpx.Response(404, request=request, json={"detail": "fake data-service: no such route"})
    HITS["other"].append(host)
    raise httpx.ConnectError("live-gates: no network", request=request)

async def _async_handle(self, request):
    return _answer(request)
httpx.AsyncHTTPTransport.handle_async_request = _async_handle
httpx.HTTPTransport.handle_request = lambda self, request: _answer(request)

sys.path[:0] = [ROOT, os.path.join(ROOT, "services", "ui-api")]
os.chdir(os.path.join(ROOT, "services", "ui-api"))
spec = importlib.util.spec_from_file_location("ui_api_main_livegates", os.path.join(ROOT, "services", "ui-api", "main.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); app = mod.app
for name in ("routers.quotes", "routers.live", "routers.news_scanner"):
    m = sys.modules.get(name)
    if m is not None and hasattr(m, "_holdings_symbols"):
        m._holdings_symbols = lambda: []                 # never read the owner's book in a test
pos = sys.modules.get("routers.positions")
if pos is not None:
    pos._last_holdings_path = lambda: __import__("pathlib").Path(os.environ["ALERTS_PATH"]).with_name("last_holdings.json")

from fastapi.testclient import TestClient
c = TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50123))   # a loopback peer (http_guard)
H = {"host": "127.0.0.1:8010"}
out = []
for sc in SCENARIOS:
    MODE["ds"] = sc.get("mode", "live")
    if sc.get("alerts") is not None:
        with open(os.environ["ALERTS_PATH"], "w") as f:
            json.dump({"alerts": sc["alerts"], "history": []}, f)
    for k in HITS:
        HITS[k].clear()
    res = []
    for _ in range(sc.get("repeat", 1)):
        r = c.request(sc.get("method", "GET"), sc["path"], headers=H)
        try:
            body = r.json()
        except ValueError:
            body = None
        res.append({"status": r.status_code, "body": body})
    out.append({"name": sc["name"], "responses": res, "yahoo": list(HITS["yahoo"]), "ds": list(HITS["ds"]),
                "other": list(HITS["other"])})
print(__MARK__ + json.dumps(out, default=str), flush=True)
"""

ASKED = ["RELIANCE", "INFY", "TCS", "HDFCBANK", "WIPRO", "SBIN", "LT", "NIFTY 50", "RELIANCE.NS", "INFY.NS", "TCS.NS",
         "LT.NS"]
API_SCENARIOS: list[dict[str, Any]] = [
    {"name": "ns_live", "path": "/api/news-scanner/quotes?symbols=RELIANCE.NS,INFY.NS"},
    {"name": "us_control", "path": "/api/news-scanner/quotes?symbols=%5EGSPC"},
    {"name": "ns_delayed", "mode": "nse", "path": "/api/news-scanner/quotes?symbols=TCS.NS"},
    {"name": "ns_down", "mode": "down", "path": "/api/news-scanner/quotes?symbols=WIPRO.NS"},
    {"name": "ticks_live", "path": "/api/quotes/ticks?symbols=RELIANCE,HDFCBANK"},
    {"name": "ticks_down", "mode": "down", "path": "/api/quotes/ticks?symbols=SBIN"},
    {"name": "live_quotes_x3", "path": "/api/live/quotes?symbols=SBIN,NIFTY%2050", "repeat": 3},
    {"name": "live_status", "path": "/api/live/status"},
    {"name": "alerts_run", "method": "POST", "path": "/api/alerts/run", "alerts": {"LT": {"above": 1.0, "yahoo": "LT.NS"}}},
]


def run_api(tmp: Path, scenarios: list[dict[str, Any]] = API_SCENARIOS,
            extra_env: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    code = (API_DRIVER.replace("__ROOT__", repr(str(ROOT))).replace("__SCENARIOS__", repr(scenarios))
            .replace("__ASKED__", repr(ASKED)).replace("__MARK__", repr(API_MARK)))
    env = {**os.environ, "ALERTS_PATH": str(tmp / "price_alerts.json"), "GOLD_LOG_PATH": str(tmp / "gold_log.json"),
           "PREFS_DB": str(tmp / "prefs.sqlite"), "PAPER_TRADES_DB": str(tmp / "paper.db"),
           "BREEZE_BUDGET_DB": str(tmp / "breeze_budget.sqlite"), "PYTHONDONTWRITEBYTECODE": "1",
           "DATA_SERVICE_URL": "http://localhost:8001"}
    env.pop("SD_ACCESS_LOG", None)
    env.pop("LIVE_QUOTES_NSE", None)                    # the code default, whatever the developer's shell says
    env.update(extra_env or {})
    p = subprocess.run([P, "-c", code], capture_output=True, text=True, timeout=240, env=env, cwd=str(tmp))
    line = next((ln for ln in reversed(p.stdout.splitlines()) if ln.startswith(API_MARK)), None)
    if line is None:
        raise AssertionError(f"ui-api harness: no result (exit {p.returncode}); stderr tail: {p.stderr[-2000:]}")
    return {r["name"]: r for r in json.loads(line[len(API_MARK):])}


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    need(ROUTERS / "live.py", "LV-API")
    return run_api(tmp_path_factory.mktemp("live_api"))


def _first(res: dict[str, Any]) -> dict[str, Any]:
    return res["responses"][0]


class TestUiApiLiveBehaviourBApi:
    def test_harness_reached_nothing_outside_the_fakes(self, api: dict[str, dict[str, Any]]):
        others = {n: r["other"] for n, r in api.items() if r["other"]}
        assert not others, f"requests to hosts outside the fakes: {others}"

    def test_negative_control_the_rollback_lever_puts_nse_back_on_yahoo_and_the_tripwire_sees_it(self, tmp_path: Path):
        """LIVE_QUOTES_NSE=0 (LV-API's deploy rollback lever) restores the legacy Yahoo path for '.NS': the same harness
        must then see Yahoo asked for both names — proof that a zero above is not a blind tripwire."""
        res = run_api(tmp_path, [API_SCENARIOS[0]], extra_env={"LIVE_QUOTES_NSE": "0"})
        assert sorted(res["ns_live"]["yahoo"]) == ["INFY.NS", "RELIANCE.NS"], res["ns_live"]["yahoo"]

    def test_the_rollback_lever_defaults_to_the_live_path(self):
        src = (ROUTERS / "live.py").read_text(encoding="utf-8")
        assert re.search(r'os\.environ\.get\("LIVE_QUOTES_NSE",\s*"1"\)', src), "LIVE_QUOTES_NSE must default to the live path"

    def test_positive_control_a_us_symbol_still_reaches_yahoo(self, api: dict[str, dict[str, Any]]):
        r = api["us_control"]
        assert _first(r)["status"] == 200 and r["yahoo"], "the Yahoo tripwire saw nothing for ^GSPC: the harness is blind"
        q = (_first(r)["body"] or {}).get("quotes", {}).get("^GSPC") or {}
        assert q.get("available") and q.get("price") == 4100.0

    @pytest.mark.parametrize("name", ["ns_live", "ns_delayed", "ns_down"])
    def test_news_scanner_quotes_never_ask_yahoo_for_an_nse_symbol(self, name: str, api: dict[str, dict[str, Any]]):
        r = api[name]
        assert _first(r)["status"] == 200, _first(r)
        assert not r["yahoo"], f"{name}: Yahoo asked for {r['yahoo']} although every symbol is NSE"
        assert any(h["path"] == "/live/quotes" for h in r["ds"]) or name == "ns_down", r["ds"]

    def test_news_scanner_nse_rows_keep_their_keys_and_say_source_age_state(self, api: dict[str, dict[str, Any]]):
        quotes = (_first(api["ns_live"])["body"] or {}).get("quotes") or {}
        for sym in ("RELIANCE.NS", "INFY.NS"):
            q = quotes.get(sym) or {}
            assert q.get("available") is True and q.get("price") == 101.5, (sym, q)
            assert q.get("change_pct") == pytest.approx(1.5), (sym, q)
            assert {"source", "state"} <= set(q) and ("age_s" in q or "age" in q), (sym, sorted(q))
            assert q["source"] == "breeze_ws" and q["state"] == "live", q
        d = ((_first(api["ns_delayed"])["body"] or {}).get("quotes") or {}).get("TCS.NS") or {}
        assert d.get("source") == "nse_api" and d.get("state") == "delayed", d          # never relabelled live

    def test_live_service_down_degrades_without_yahoo(self, api: dict[str, dict[str, Any]]):
        q = ((_first(api["ns_down"])["body"] or {}).get("quotes") or {}).get("WIPRO.NS") or {}
        assert q.get("source") != "yahoo" and q.get("state") in (None, "unavailable", "stale", "closed"), q
        assert not (q.get("available") and q.get("state") == "live"), q

    @pytest.mark.parametrize("name", ["ticks_live", "ticks_down"])
    def test_quotes_ticks_never_reach_yahoo(self, name: str, api: dict[str, dict[str, Any]]):
        r = api[name]
        assert _first(r)["status"] == 200 and not r["yahoo"], (name, r["yahoo"])
        rows = (_first(r)["body"] or {}).get("ticks") or (_first(r)["body"] or {}).get("quotes") or {}
        assert all((v or {}).get("source") != "yahoo" for v in rows.values()), rows

    def test_quotes_ticks_answer_from_the_live_service(self, api: dict[str, dict[str, Any]]):
        body = _first(api["ticks_live"])["body"] or {}
        rows = body.get("ticks") or body.get("quotes") or {}
        assert (rows.get("RELIANCE") or {}).get("price") == 101.5, rows

    def test_live_quotes_shape_and_one_upstream_read_per_two_seconds(self, api: dict[str, dict[str, Any]]):
        r = api["live_quotes_x3"]
        assert [x["status"] for x in r["responses"]] == [200, 200, 200]
        body = r["responses"][0]["body"]
        assert {"as_of", "market", "quotes"} <= set(body) and body["market"]["state"] in MARKET_STATES
        for sym in ("SBIN", "NIFTY 50"):
            q = body["quotes"][sym]
            assert QUOTE_KEYS <= set(q), (sym, sorted(QUOTE_KEYS - set(q)))
            assert q["source"] in SOURCES and q["state"] in STATES
        upstream = [h for h in r["ds"] if h["path"] == "/live/quotes"]
        assert len(upstream) == 1, f"3 reads inside 2 s cost {len(upstream)} data-service requests (SWR ≤ 2 s, single flight)"
        assert not r["yahoo"]

    def test_live_status_shape(self, api: dict[str, dict[str, Any]]):
        body = _first(api["live_status"])["body"] or {}
        assert _first(api["live_status"])["status"] == 200 and STATUS_KEYS <= set(body), sorted(STATUS_KEYS - set(body))
        assert body["state"] in FEED_STATES

    def test_server_price_alerts_price_nse_names_from_the_live_service(self, api: dict[str, dict[str, Any]]):
        r = api["alerts_run"]
        body = _first(r)["body"] or {}
        assert _first(r)["status"] == 200 and not r["yahoo"], (body, r["yahoo"])
        assert body.get("priced") == 1 and [h.get("sym") for h in body.get("hits", [])] == ["LT"], body


PUSH_DRIVER = r"""
import asyncio, json, os, socket, sys
ROOT = __ROOT__
socket.socket.connect = lambda self, addr: (_ for _ in ()).throw(OSError("live-gates: network refused"))
sys.path[:0] = [ROOT, os.path.join(ROOT, "services", "ui-api")]
os.chdir(os.path.join(ROOT, "services", "ui-api"))
from routers import live

async def main():
    c = live.PushClient(queue_max=live.PUSH_QUEUE_MAX)
    c.set_symbols(["SBIN"])
    for i in range(100):                                   # a client that never reads
        c.offer({"type": "quotes", "seq": i})
    kept = []
    while not c.queue.empty():
        kept.append(c.queue.get_nowait()["seq"])
    payload = {"as_of": "x", "market": {"state": "open"}, "quotes": {"SBIN": {"price": 1.0, "state": "live"}}}
    c.feed(payload, 1000.0)
    first = c.queue.get_nowait()
    c.feed(payload, 1001.0)                                # unchanged row inside the full-snapshot window: nothing sent
    unchanged_sent = not c.queue.empty()
    return {"max": live.PUSH_QUEUE_MAX, "kept": kept, "dropped": c.dropped, "interval": live.PUSH_INTERVAL_S,
            "first_full": first.get("full"), "first_type": first.get("type"), "unchanged_sent": unchanged_sent,
            "max_clients": getattr(live, "PUSH_MAX_CLIENTS", None)}

print(__MARK__ + json.dumps(asyncio.run(main())), flush=True)
"""


def test_push_channel_queues_are_bounded_drop_oldest_and_paced(tmp_path: Path):
    """The optional 'quotes' WebSocket channel (contract: per-client bounded queue, drop-oldest; polling stays the
    baseline; ≤ one data-service request per symbol batch per 2 s)."""
    need(ROUTERS / "live.py", "LV-API")
    if "class PushClient" not in (ROUTERS / "live.py").read_text(encoding="utf-8"):
        pytest.fail("routers/live.py has no PushClient: the push channel was deferred — record it in the contract notes")
    code = PUSH_DRIVER.replace("__ROOT__", repr(str(ROOT))).replace("__MARK__", repr(API_MARK))
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "ALERTS_PATH": str(tmp_path / "a.json"),
           "PREFS_DB": str(tmp_path / "p.sqlite"), "BREEZE_BUDGET_DB": str(tmp_path / "b.sqlite")}
    p = subprocess.run([P, "-c", code], capture_output=True, text=True, timeout=120, env=env, cwd=str(tmp_path))
    line = next((ln for ln in reversed(p.stdout.splitlines()) if ln.startswith(API_MARK)), None)
    assert line is not None, f"push harness: no result (exit {p.returncode}); stderr: {p.stderr[-1500:]}"
    r = json.loads(line[len(API_MARK):])
    assert 1 <= r["max"] <= 256 and len(r["kept"]) == r["max"], r                     # bounded
    assert r["kept"] == list(range(100 - r["max"], 100)) and r["dropped"] == 100 - r["max"], r   # oldest dropped
    assert r["first_type"] == "quotes" and r["first_full"] is True and r["unchanged_sent"] is False, r
    assert r["interval"] >= 2.0, r                                                    # never faster than the 2 s SWR
    assert r["max_clients"] is None or r["max_clients"] >= 1


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# the machinery itself (synthetic sources; must be green at all times)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
class TestGateMachinery:
    def _graph(self, **mods: str) -> CallGraph:
        return CallGraph({k: load_module(k, textwrap.dedent(v)) for k, v in mods.items()})

    def test_call_graph_follows_imports_aliases_and_partial(self):
        g = self._graph(
            news_scanner='''
                import functools
                async def _yahoo_chart(sym):
                    """docstring mentioning https://query1.finance.yahoo.com is prose"""
                    return await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}")
                async def _fetch_quote(sym):
                    return await _yahoo_chart(sym)
                async def get_quotes(symbols):
                    return await cache.get(symbols, functools.partial(_fetch_quote, symbols))
                def doc_only():
                    """https://query2.finance.yahoo.com"""
                    return 1
            ''',
            quotes='''
                from routers.news_scanner import get_quotes as _yq
                async def ticks(symbols):
                    return await _yq(",".join(f"{s}.NS" for s in symbols))
            ''',
            gold='''
                from routers import news_scanner as ns
                async def f():
                    return await ns._yahoo_chart("GC=F")
            ''',
        )
        assert g.yahoo_sinks(("quotes", "ticks")) == ["news_scanner._yahoo_chart"]          # alias + partial + 3 deep
        assert g.yahoo_sinks(("gold", "f")) == ["news_scanner._yahoo_chart"]                # module alias attribute
        assert g.yahoo_sinks(("news_scanner", "doc_only")) == []                            # docstrings are prose
        hits = nse_symbol_calls(g)
        assert [(m, f, c) for m, f, _, c in hits] == [("quotes", "ticks", ("news_scanner", "get_quotes"))]
        assert not g.reaches_text(("quotes", "ticks"), LIVE_SERVICE_TEXT)

    def test_nse_taint_through_a_local_name_and_the_live_text(self):
        g = self._graph(
            news_scanner='''
                async def _yahoo_chart(sym):
                    return await c.get("https://query2.finance.yahoo.com/v8/finance/chart/" + sym)
                async def _live(syms):
                    return await get_json(f"{DATA}/live/quotes", params={"symbols": syms})
                async def get_quotes(symbols):
                    nse = [s for s in symbols.split(",") if s.endswith(".NS")]
                    return await _live(nse), await _yahoo_chart(symbols)
            ''',
            alerts='''
                from routers.news_scanner import get_quotes, _yahoo_chart
                async def run(alerts):
                    yahoo = {s: f"{s}.NS" for s in alerts}
                    a = await get_quotes(symbols=",".join(yahoo.values()))
                    b = await _yahoo_chart(yahoo["X"])
                    c = await _yahoo_chart("GC=F")
                    return a, b, c
            ''',
        )
        hits = [(m, f, c) for m, f, _, c in nse_symbol_calls(g)]
        assert ("alerts", "run", ("news_scanner", "get_quotes")) in hits
        assert ("alerts", "run", ("news_scanner", "_yahoo_chart")) in hits                  # direct: a violation
        assert len(hits) == 2                                                               # "GC=F" is not NSE
        assert g.reaches_text(("news_scanner", "get_quotes"), LIVE_SERVICE_TEXT)
        assert not g.reaches_text(("alerts", "run"), re.compile("/nothing/"))

    def test_call_graph_through_classes_and_module_attributes(self):
        g = self._graph(
            live='''
                class Hub:
                    async def quotes(self, syms):
                        return await self._fetch(syms)
                    async def _fetch(self, syms):
                        return await get_json(f"{DS}/live/quotes", params={"symbols": syms})
                _HUB = None
                def hub():
                    return Hub()
            ''',
            quotes='''
                from routers import live
                async def ticks(symbols):
                    return await live.hub().quotes(symbols)
            ''',
            bad='''
                class Y:
                    async def get(self, s):
                        return await c.get("https://query1.finance.yahoo.com/v8/finance/chart/" + s)
                async def handler(s):
                    return await Y().get(s)
            ''',
        )
        assert g.reaches_text(("quotes", "ticks"), LIVE_SERVICE_TEXT)                       # module attr → class methods
        assert g.yahoo_sinks(("quotes", "ticks")) == []
        assert g.yahoo_sinks(("bad", "handler")) == ["bad.Y.get"]                           # a class sink is seen
        assert g.exists(("live", "Hub")) and g.exists(("live", "Hub._fetch")) and not g.exists(("live", "nope"))

    def test_route_table_from_decorators_prefixes_and_aliases(self):
        main = 'from routers import alerts as price_alerts, quotes\napp.include_router(quotes.router, prefix="/api/quotes")\n' \
               'app.include_router(price_alerts.router, prefix="/api/alerts")\n' \
               'app.include_router(quotes.extra_router, prefix="/api/x")\n'
        pre = include_prefixes(main)
        assert pre == {"quotes": "/api/quotes", "alerts": "/api/alerts", "quotes.extra_router": "/api/x"}
        g = self._graph(quotes='''
            router = APIRouter()
            extra_router = APIRouter(prefix="/sub")
            @router.get("/live")
            @router.get("/ticks")
            async def live_quotes(symbols):
                return 1
            @extra_router.get("/y")
            def y():
                return 2
        ''', alerts='''
            @router.post("/run")
            async def run():
                return 1
        ''')
        r = g.routes(pre)
        assert r["/api/quotes/ticks"] == r["/api/quotes/live"] == ("quotes", "live_quotes")
        assert r["/api/x/sub/y"] == ("quotes", "y") and r["/api/alerts/run"] == ("alerts", "run")

    def test_inventory_parser(self):
        text = "## 5. Full inventory (2 rows)\n\n| P | Page | Pane | UI file | API route(s) | Current | Lag | live_capable | Target |\n" \
               "|---|---|---|---|---|---|---|---|---|\n" \
               "| 1 | ALL | NIFTY | `ui/components/A.tsx (NiftyLive)` | r | c | l | **yes-breeze** | t |\n" \
               "| 9 | CHRT | Intraday | `ui/components/B.tsx, ui/lib/c.ts` | r | c | l | **eod-only** | t |\n\n## 6. next\n"
        rows = parse_inventory(text)
        assert [(r.ui_files, r.live_capable) for r in rows] == [(("ui/components/A.tsx",), "yes-breeze"),
                                                                (("ui/components/B.tsx", "ui/lib/c.ts"), "eod-only")]
        assert live_rows(rows) == rows[:1]

    def test_chip_detection_parent_panels_and_comments(self):
        assert renders_chip("<Panel title='x' source={sourceOf(d.as_of, { source: 'NSE' })}>")
        assert not renders_chip("<Panel title='x' badge={'context'}>")
        assert renders_chip('<span data-feed={chip.tone}>') and renders_chip("<SourceChip info={s} />")
        assert not renders_chip(strip_ts_comments("// <SourceChip info={s} />\n{/* <SourceChip /> */}\n"))
        parent = "<Panel title='a' source={x}><Foo /></Panel><Panel title='b'><Bar /></Panel>" \
                 "<Panel title='c' source={y} badge='z'><div><Panel title='inner'><Baz/></Panel></div></Panel>"
        assert enclosed_in_sourced_panel(parent, "Foo") is True
        assert enclosed_in_sourced_panel(parent, "Bar") is False
        assert enclosed_in_sourced_panel(parent, "Baz") is False                           # nearest Panel has no source
        assert enclosed_in_sourced_panel(parent, "Qux") is None
        assert enclosed_in_sourced_panel("<Panel source={a > b ? x : y}><Foo/></Panel>", "Foo") is True   # '>' in {}
        assert enclosed_in_sourced_panel("<Panel source={s} /><Foo/>", "Foo") is False      # self-closing ≠ open
        assert enclosed_in_sourced_panel("const r = useState<Foo>(null); let x: Promise<Foo> | null", "Foo") is None
        assert enclosed_in_sourced_panel("useLoad<Foo | null>(f); type A = Array<Foo>", "Foo") is None
        assert component_names("export function IndexIntraday() {}\nexport const Big = () => 1\nfunction low() {}") == \
            ["IndexIntraday", "Big"]

    def test_hook_detection_names_the_live_module_not_a_same_named_hook(self):
        a = UI / "components" / "Zed.tsx"
        ctx = "import { useLiveQuotes } from '@/context/AppContext'\nimport { type LiveQuote } from '@/lib/liveQuotes'\n" \
              "export function Zed() { const { liveQuotes } = useLiveQuotes(); return null }"
        assert not uses_hook(a, {a: ctx})                                                  # AppContext's hook ≠ live hook
        aliased = "import { useLiveQuotes as useNse, type LiveQuote } from '@/lib/liveQuotes'\nexport function Zed() { useNse(['X']) }"
        assert uses_hook(a, {a: aliased}) and hook_locals(aliased) == {"useNse"}
        imported_only = "import { useLiveQuotes } from '@/lib/liveQuotes'\nexport function Zed() { return null }"
        assert not uses_hook(a, {a: imported_only})                                        # imported, never called

    def test_live_chip_derivation(self):
        a = UI / "components" / "Zed.tsx"
        good = "import { useLiveQuotes } from '@/lib/liveQuotes'\nconst lq = useLiveQuotes(s)\n<Panel source={lq.source}>"
        assert derives_live_chip(a, {a: good})
        assert derives_live_chip(a, {a: "const l = lq.lineFor(sym)"})
        assert not derives_live_chip(a, {a: "import { useLiveQuotes } from '@/lib/liveQuotes'\n<Panel source={sourceOf(x)}>"})

    def test_hook_detection(self, tmp_path: Path):
        a = UI / "components" / "Zed.tsx"
        b = UI / "components" / "ZedRow.tsx"
        srcs = {a: "import { ZedRow } from '@/components/ZedRow'\nexport function Zed() { return <ZedRow/> }",
                b: "import { useLiveQuotes } from '@/lib/liveQuotes'\nexport function ZedRow() { useLiveQuotes(['X']) }"}
        assert uses_hook(b, srcs) and uses_hook(a, srcs)                                    # one level of composition
        srcs2 = {a: srcs[a], b: "export function ZedRow() { return null }"}
        assert not uses_hook(a, srcs2) and not uses_hook(b, srcs2)
        srcs3 = {a: strip_ts_comments("// import { useLiveQuotes } from '@/lib/liveQuotes'\nexport function Zed() {}")}
        assert not uses_hook(a, srcs3)                                                      # a comment is not adoption

    def test_contract_row_checker_rejects_dishonest_rows(self):
        ok = {k: None for k in QUOTE_KEYS} | {"price": 1.0, "source": "breeze_ws", "state": "live", "age_s": 1.0,
                                             "ltt": "2026-11-05T10:00:00+05:30"}
        assert_contract_row("X", ok)
        bad = [
            {**ok, "source": "nse_api"},                                   # NSE website labelled live
            {**ok, "age_s": 30.0},                                         # an old tick live without a reason
            {**ok, "age_s": 130.0, "reason": "quiet: 130 s"},              # quiet past 120 s
            {**ok, "state": "delayed", "source": "nse_api", "age_s": 95.0},  # delayed past 90 s
            {**ok, "ltt": "2026-11-05T10:00:00"},                          # no IST offset
            {**ok, "source": "yahoo", "state": "delayed"},                 # not a contract source
            {k: v for k, v in ok.items() if k != "value_cr"},              # a contract key missing
        ]
        for row in bad:
            with pytest.raises(AssertionError):
                assert_contract_row("X", row)
        assert_contract_row("X", {**ok, "age_s": 60.0, "reason": "quiet: no new trade or quote for 60 s"})

    def test_nse_live_site_counter(self):
        assert nse_live_sites("sourceOf(x, { source: 'NSE', live: true })") == 1
        assert nse_live_sites("sourceOf(x, { live: !!d.market_open, source: 'NSE' })") == 1
        assert nse_live_sites("sourceOf(d.live ? a : b, { source: d.live ? 'NSE' : 'NSE F&O bhavcopy', live: !!d.live })") == 1
        assert nse_live_sites("sourceOf(x, { source: 'NSE', live: false, hint: e })") == 0
        assert nse_live_sites("sourceOf(x, { source: 'NSE EOD' })") == 0
        assert nse_live_sites("sourceOf(m.as_of, { live: true, source: 'BREEZE' })") == 0
        assert nse_live_sites("sourceOf(f(a, b), { source: 'NSE pre-open', live: auctionPhase(now).live })") == 1
