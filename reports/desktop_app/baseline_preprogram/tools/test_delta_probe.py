"""delta_probe.py is GET-only by enforcement, not by luck (FX-QA adversarial check): every context it opens aborts
any /api request that is not GET/HEAD/OPTIONS before the first navigation, so probing a tab that POSTs on load
(OSTR, ALFA, MCXG) against the live ui-api sends it no write. Pure: fake Playwright objects, no browser.

Run: /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest reports/desktop_app/baseline_preprogram/tools -q
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest

dp = importlib.import_module("delta_probe")


class FakeRoute:
    def __init__(self, method: str, url: str) -> None:
        self.request = SimpleNamespace(method=method, url=url)
        self.outcome: str | None = None

    def continue_(self) -> None:
        self.outcome = "continued"

    def abort(self, reason: str) -> None:
        self.outcome = f"aborted:{reason}"


class FakeContext:
    def __init__(self) -> None:
        self.routes: list[tuple[Any, Any]] = []
        self.calls: list[str] = []

    def route(self, pattern: Any, handler: Any) -> None:
        self.calls.append("route")
        self.routes.append((pattern, handler))

    def add_init_script(self, _script: str) -> None:
        self.calls.append("init_script")

    def new_page(self) -> Any:
        self.calls.append("new_page")
        raise RuntimeError("stop here: the guard must already be installed")


def _handler(ctx: FakeContext, blocked: list[str]) -> Any:
    dp.install_get_only_guard(ctx, blocked)
    assert len(ctx.routes) == 1
    return ctx.routes[0]


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post"])
def test_non_get_api_requests_are_aborted_and_recorded(method: str) -> None:
    blocked: list[str] = []
    _pattern, handler = _handler(FakeContext(), blocked)
    route = FakeRoute(method, "http://127.0.0.1:8010/api/options/strategy/analyze?x=1")
    handler(route)
    assert route.outcome == "aborted:blockedbyclient"
    assert blocked == [f"{method} /api/options/strategy/analyze"]


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_safe_requests_continue(method: str) -> None:
    blocked: list[str] = []
    _pattern, handler = _handler(FakeContext(), blocked)
    route = FakeRoute(method, "http://127.0.0.1:8010/api/desk/status")
    handler(route)
    assert route.outcome == "continued" and blocked == []


def test_the_route_pattern_covers_api_on_any_host_and_nothing_else() -> None:
    pattern, _ = _handler(FakeContext(), [])
    assert pattern.match("http://127.0.0.1:8010/api/alpha/scan")
    assert pattern.match("http://127.0.0.1:8097/api/mcx/ticket")      # a scratch server too
    assert not pattern.match("http://127.0.0.1:8010/_next/static/chunks/a.js")
    assert not pattern.match("http://127.0.0.1:8010/health")
    assert not pattern.match("https://fonts.gstatic.com/s/api/x.woff2")


def test_visit_installs_the_guard_before_the_page_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = FakeContext()
    probe = SimpleNamespace(new_qa_context=lambda _browser, **_kw: ctx)
    monkeypatch.setattr(dp, "qa_probe", lambda: probe)
    with pytest.raises(RuntimeError, match="stop here"):
        dp.visit(object(), "http://127.0.0.1:8010", "ostrategy", "OSTR", 0.0)
    assert ctx.calls[:2] == ["route", "init_script"] and ctx.calls[-1] == "new_page"


def test_markdown_lists_refused_requests() -> None:
    side: dict[str, Any] = {"ready_ms": 1, "fcp_ms": 1, "gate": None, "html": {"sd_shell": None, "shell_top": None, "inline_style": None},
            "body": {"padding_top": "0px", "inline_style": None}, "font_files": [], "fonts_loaded": [],
            "toast_rules_in_css": {}, "local_storage_keys": [], "api_requests": 0, "non_api_requests": {}}
    report = {"meta": {"a": "A", "b": "B", "tab": "ostrategy", "observe_s": 1},
              "engines": {"chromium": {"version": "1", "a": dict(side, blocked_non_get=["POST /api/options/strategy/analyze"]),
                                       "b": dict(side, blocked_non_get=[])}}}
    md = dp.to_markdown(report)
    assert "non-GET /api requests refused by the probe | POST /api/options/strategy/analyze | none |" in md
