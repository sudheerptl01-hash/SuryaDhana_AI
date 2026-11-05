"""G5 addition: "Yahoo absent from ``/db/market-monitor``" (PLAN 1.7; R-ARCH: a Yahoo chart call ran on that route's locked
request path). B1's ``tests/test_hosts_allowlist_terminal.py`` scans the new packages and B7's
``tests/arch/test_hosts_allowlist_shared.py`` scans ``shared/``; neither looks at the route. This walks the route handler in
``services/data-service/main.py`` and every module-level function of ``main.py`` it reaches (transitively), plus
``market_monitor.py``, and fails on any Yahoo provider / fetcher / host name. Static (AST), so nothing is imported or called."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "services" / "data-service" / "main.py"
MONITOR = ROOT / "services" / "data-service" / "market_monitor.py"
ROUTE = "/db/market-monitor"

#: names / strings that mean "this code path fetches from Yahoo"
YAHOO_NAMES = {"get_yfinance", "_yfinance", "DirectYahooProvider", "yfinance", "yf"}
YAHOO_TEXT = re.compile(r"query[12]\.finance\.yahoo|finance\.yahoo\.com|/v8/finance/chart|\^CRSLDX|\^NSEI|\^INDIAVIX",
                        re.IGNORECASE)


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}


def _route_handler(tree: ast.Module, path: str) -> str | None:
    for name, fn in _functions(tree).items():
        for dec in fn.decorator_list:
            if isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Constant) and dec.args[0].value == path:
                return name
    return None


def reachable(tree: ast.Module, root: str) -> set[str]:
    """Module-level functions reachable from ``root`` by plain-name calls or references (``Depends(get_store)`` included)."""
    fns = _functions(tree)
    seen, todo = set(), [root]
    while todo:
        name = todo.pop()
        if name in seen or name not in fns:
            continue
        seen.add(name)
        for node in ast.walk(fns[name]):
            if isinstance(node, ast.Name) and node.id in fns:
                todo.append(node.id)
    return seen


def yahoo_hits(src: str, root: str) -> list[str]:
    tree = ast.parse(src)
    fns = _functions(tree)
    hits: list[str] = []
    for name in sorted(reachable(tree, root)):
        fn = fns[name]
        for node in ast.walk(fn):
            ident = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
            if ident in YAHOO_NAMES:
                hits.append(f"{name}:{getattr(node, 'lineno', fn.lineno)} {ident}")
            if isinstance(node, ast.arg) and node.arg in YAHOO_NAMES:
                hits.append(f"{name}:{fn.lineno} arg {node.arg}")
        first = fn.body[0] if fn.body else None
        doc = first.value if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) else None
        for node in ast.walk(fn):                       # string literals the code uses (the docstring and comments are prose)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node is not doc:
                for m in YAHOO_TEXT.finditer(node.value):
                    hits.append(f"{name}:{node.lineno} text {m.group(0)}")
    return hits


def test_the_route_handler_is_found_and_reaches_its_helpers():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    handler = _route_handler(tree, ROUTE)
    assert handler == "market_monitor_snapshot"
    reach = reachable(tree, handler)
    assert {"market_monitor_snapshot", "_nifty500_nse", "get_store"} <= reach, reach


def test_no_yahoo_on_the_market_monitor_request_path():
    src = MAIN.read_text(encoding="utf-8")
    handler = _route_handler(ast.parse(src), ROUTE)
    assert handler is not None
    hits = yahoo_hits(src, handler)
    assert not hits, f"Yahoo on the {ROUTE} request path: {hits}"


def test_market_monitor_module_has_no_yahoo_caller():
    text = MONITOR.read_text(encoding="utf-8")
    bad = [m.group(0) for m in YAHOO_TEXT.finditer(text)] + [w for w in ("yfinance", "DirectYahooProvider", "get_yfinance")
                                                             if re.search(rf"\b{w}\b", text)]
    assert not bad, bad


def test_negative_control_the_scanner_sees_a_yahoo_helper_two_calls_deep():
    bad = '''
@app.get("/db/market-monitor")
def snap(store=Depends(get_store)):
    return _helper()

def _helper():
    return _deeper()

def _deeper():
    """Yahoo's ^CRSLDX in a docstring is prose, not a call."""
    yf = get_yfinance()
    return yf.history("^CRSLDX")

def get_store():
    return None

def get_yfinance():
    return None
'''
    hits = yahoo_hits(bad, "snap")
    assert any("_deeper" in h and "get_yfinance" in h for h in hits) and any("^CRSLDX" in h for h in hits), hits
    assert yahoo_hits(bad.replace("return _helper()", "return None"), "snap") == []
    assert sum("^CRSLDX" in h for h in hits) == 1, "the docstring mention is not a hit; the literal argument is"
