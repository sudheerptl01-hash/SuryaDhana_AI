"""The live-quote provider's Breeze calls must be metered — and a refusal must not be amplified.

F9-03: `providers/icici_breeze_provider.py` held three unmetered `self._breeze.*` calls on the busiest Breeze
path in the stack — the live-quote method that `main.py`'s NIFTY and watchlist pollers drive every 15 s, whose
own comment prices it at ~1,580 calls a day (32 % of the daily quota). The shared ledger, the budget panel and
the 100/min · 5,000/day guard could not see a single one, so `/api/positions/breeze-budget` reported thousands
of calls remaining while that volume drained the real quota. On a trading day the first symptom would have been
the option chain and margin failing mid-session with the panel still showing plenty left.

Metering it introduced a second trap worth pinning: the ledger's `BudgetExceeded` is a `RuntimeError`, and
these methods retried on `RuntimeError` — so a refusal would have become three attempts with exponential
backoff, each asking the ledger again. A refusal is a decision, not a transient fault.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DS = Path(__file__).resolve().parents[1]
REPO = DS.parents[1]
for p in (str(REPO), str(DS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.breeze_budget import BudgetExceeded              # noqa: E402
import providers.icici_breeze_provider as prov               # noqa: E402


def _provider(sdk: object) -> object:
    p = prov.ICICIBreezeProvider.__new__(prov.ICICIBreezeProvider)
    p._breeze = sdk
    p._require_connection = lambda: None
    p._resolve_isec_code = lambda t: "INFY"
    return p


def test_every_sdk_call_in_the_provider_is_inside_a_ledger_guard() -> None:
    """The source-level check, so a new call site cannot quietly skip the guard."""
    # Counted on CODE lines only: a bare `src.count(...)` could be restored by a comment carrying the
    # literal, which is the F8-02 defect in miniature. The ui-api gate catches the real mutation either way;
    # this is the local, fast check and it should not be the weaker one.
    src = Path(prov.__file__).read_text(encoding="utf-8")
    code = "\n".join(ln.split("#", 1)[0] for ln in src.split("\n"))
    assert code.count("ledger().guard(") == 3, "a Breeze call site was added or lost its guard"
    for method in ("get_quotes", "get_historical_data_v2"):
        assert f'self._breeze.{method}(' in src
    # the guard must come BEFORE the call, not after it
    for marker in ('with ledger().guard("data-service.live_quote", "get_quotes"):',
                   'with ledger().guard("data-service.intraday", "get_historical_data_v2"):',
                   'with ledger().guard("data-service.history", "get_historical_data_v2"):'):
        assert marker in src, marker


def test_the_retry_predicate_retries_faults_but_never_a_refusal() -> None:
    refusal = BudgetExceeded(SimpleNamespace(reason="per-day cap reached", allowed=False))
    assert prov._retry_real_errors(RuntimeError("transient")) is True
    assert prov._retry_real_errors(refusal) is False, "a budget refusal must not be retried"
    assert prov._retry_real_errors(ValueError("x")) is False


def test_a_transient_fault_still_retries_three_times() -> None:
    """The control: the fix must not have disabled the retry it narrowed."""
    seen = {"n": 0}

    class Flaky:
        def get_quotes(self, **kw):
            seen["n"] += 1
            raise RuntimeError("transient")

    with pytest.raises(RuntimeError):
        _provider(Flaky()).get_live_quote("INFY")
    assert seen["n"] == 3, f"the retry stopped working: {seen['n']} attempts"


def test_a_refusal_asks_the_ledger_once_and_never_reaches_the_sdk(monkeypatch) -> None:
    asked, called = {"n": 0}, {"n": 0}

    class Refusing:
        def guard(self, caller: str, method: str = ""):
            asked["n"] += 1
            raise BudgetExceeded(SimpleNamespace(reason="cap", allowed=False))

    class Sdk:
        def get_quotes(self, **kw):
            called["n"] += 1
            return {}

    monkeypatch.setattr(prov, "ledger", lambda: Refusing())
    with pytest.raises(BudgetExceeded):
        _provider(Sdk()).get_live_quote("INFY")
    assert asked["n"] == 1, f"the refusal was retried {asked['n']}x — exactly what the predicate must prevent"
    assert called["n"] == 0, "the SDK was called despite the refusal"


# ── the start-up warm-ups must actually call what they think they call ──────────────────────────────────────
# Found 14 Nov in the data-service log, not by a critic: every start logged
#   "Market monitor warm-up failed: 'Depends' object has no attribute 'get_bhavcopy_meta'"
# because `_warm_monitor` called the ROUTE HANDLER positionally — `market_monitor_snapshot(_store)` — so the
# store landed in `as_of` and `store` kept its unresolved `Depends(get_store)` default. The warm-up existed to
# spare the first BRIEF/MKT visit a ~5 s cold cache and had never once worked; its own forgiving `except` said
# "a cold cache is only slower, never broken", which is true and is precisely why nobody looked.

def test_no_route_handler_is_called_with_its_dependency_left_unresolved() -> None:
    """Any call to a route handler from non-request code must give every `Depends` parameter a value.

    Scoped to EVERY module of both services, not just the one file the bug was found in: F9's lesson was that
    three rounds hardened a gate's logic while never asking what it did not look at. The rule is the real one —
    a `Depends` parameter must be filled by keyword OR by a positional list long enough to reach it, so
    `financials_latest(symbols, store)` and `index_contribution(index, store)` stay correct and unflagged.
    A gate that cried about those is one the next author learns to skip.
    """
    import ast

    roots = (REPO / "services/ui-api", REPO / "services/data-service")
    offenders: list[str] = []
    scanned = 0
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if "/tests/" in str(path):
                continue
            scanned += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:                                    # pragma: no cover — mid-edit file
                continue
            dep_params: dict[str, dict[str, int]] = {}
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.args.defaults:
                    continue
                args, defaults = node.args.args, node.args.defaults
                for arg, default in zip(args[-len(defaults):], defaults, strict=True):
                    if isinstance(default, ast.Call) and getattr(default.func, "id", "") == "Depends":
                        dep_params.setdefault(node.name, {})[arg.arg] = [a.arg for a in args].index(arg.arg)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in dep_params):
                    continue
                named = {k.arg for k in node.keywords}
                for param, pos in dep_params[node.func.id].items():
                    if param not in named and len(node.args) <= pos:
                        offenders.append(f"{path.relative_to(REPO)}:{node.lineno} {node.func.id}() leaves "
                                         f"`{param}` as its unresolved Depends default")
    assert scanned > 100, f"only {scanned} service modules scanned — are the roots right?"
    assert not offenders, offenders


def test_startup_warmups_pass_fastapi_dependencies_by_keyword() -> None:
    """Any call to a route handler from non-request code must name `store=`, or it silently gets a `Depends`."""
    import ast

    src = (DS / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    # every route handler that takes a `store: ... = Depends(...)` parameter
    handlers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg, default in zip(node.args.args[-len(node.args.defaults):] if node.args.defaults else [],
                                    node.args.defaults, strict=True):
                if (isinstance(default, ast.Call) and getattr(default.func, "id", "") == "Depends"
                        and arg.arg == "store"):
                    handlers.add(node.name)
    assert "market_monitor_snapshot" in handlers, "the handler this test is about changed shape"

    # …whose `store` parameter is left to its Depends default is the bug. A positional call is fine when it
    # reaches that far: `financials_latest(symbols, store)` and `index_contribution(index, store)` are correct,
    # and a gate that flagged them too would be noise the next author learns to skip.
    positions = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in handlers:
            positions[node.name] = [a.arg for a in node.args.args].index("store")

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in handlers):
            continue
        if any(k.arg == "store" for k in node.keywords):
            continue                                       # named explicitly: correct
        if len(node.args) > positions[node.func.id]:
            continue                                       # positional, and it reaches `store`: correct
        offenders.append(f"{node.func.id}() at main.py:{node.lineno} leaves `store` as its Depends default")
    assert not offenders, (
        "a route handler with a Depends-injected `store` is being called positionally, so it will receive the "
        f"unresolved Depends object instead of the store: {offenders}")
