"""QA tool defaults after the switchover (FX-OPS): ui_audit targets the live terminal on :8010, parity keeps :3000
as its reference but says how to get one, and ui_perf pins the UI's settings sync to readonly in every context
(desktop review C3-logic-unchanged-08 / -09). Pure: no browser, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ui_audit
import ui_perf
from desktop_qa import parity
from desktop_qa.probe import PREFS_MODE_KEY


def test_ui_audit_defaults_to_the_live_terminal():
    ap = ui_audit.build_parser()
    assert ap.parse_args([]).base == "http://127.0.0.1:8010"
    assert ap.parse_args(["--base", "http://localhost:3000"]).base == "http://localhost:3000"   # still selectable
    assert ap.parse_args([]).prefs_mode == "readonly"


def test_parity_reference_stays_3000_and_explains_how_to_get_one():
    ap = parity.build_parser()
    assert ap.parse_args(["--b", "http://127.0.0.1:8010", "--out", "x"]).a == "http://localhost:3000"
    help_a = ap._option_string_actions["--a"].help
    assert "start frontend" in help_a and "scratch_server" in help_a


class FakeContext:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.scripts: list[str] = []
        self.ws_routes: list[Any] = []

    def add_init_script(self, script: str) -> None:
        self.scripts.append(script)

    def route_web_socket(self, url: Any, handler: Any) -> None:
        self.ws_routes.append(url)


class FakeBrowser:
    def __init__(self) -> None:
        self.contexts: list[FakeContext] = []

    def new_context(self, **kwargs: Any) -> FakeContext:
        self.contexts.append(FakeContext(**kwargs))
        return self.contexts[-1]


def test_ui_perf_contexts_are_readonly_by_default():
    assert ui_perf.build_parser().parse_args([]).prefs_mode == "readonly"
    b = FakeBrowser()
    ctx = ui_perf.new_perf_context(b, {"width": 1600, "height": 1000})
    assert ctx.kwargs == {"viewport": {"width": 1600, "height": 1000}, "ignore_https_errors": False}
    # the prefs pin runs first (before any page script), then the perf instrumentation
    assert len(ctx.scripts) == 2 and PREFS_MODE_KEY in ctx.scripts[0] and "'readonly'" in ctx.scripts[0]
    assert ctx.scripts[1] == ui_perf.INIT_SCRIPT
    assert len(ctx.ws_routes) == 1      # every WebSocket mocked (R-OPS-09): a perf run opens 0 live monitor sockets


def test_ui_perf_prefs_mode_flag():
    assert ui_perf.build_parser().parse_args(["--prefs-mode", "off"]).prefs_mode == "off"
    off = ui_perf.new_perf_context(FakeBrowser(), {"width": 1, "height": 1}, "off")
    assert "'off'" in off.scripts[0]
    sync = ui_perf.new_perf_context(FakeBrowser(), {"width": 1, "height": 1}, "sync")   # scratch servers only
    assert sync.scripts == [ui_perf.INIT_SCRIPT]
    with pytest.raises(SystemExit):
        ui_perf.build_parser().parse_args(["--prefs-mode", "write"])
