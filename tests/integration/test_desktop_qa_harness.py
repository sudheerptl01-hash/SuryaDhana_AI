"""Unit tests for the desktop QA harness itself (scripts/desktop_qa, scripts/ui_audit.py).

Pure and fast: no browser, no live stack, no network (the scratch server is exercised through an
``httpx.MockTransport`` backend). They pin the failure policy (what the 43-page gate counts), the parity
comparison (incl. the gold program's NEW page and intended structure deltas), the stream parsers, the self-test
JSON contract and the ACL resolver.
"""
from __future__ import annotations

import gzip
import json
import plistlib
import re
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ui_audit
from desktop_qa import netpolicy, pages, parity, run_selftest, scratch_server, streams, tauri_acl
from desktop_qa.probe import failure_lines, normalize_fingerprint

BASE = "http://localhost:3000"


# ── pages ──────────────────────────────────────────────────────────────────────────────────────────

TSX = """
const TAB_IDS: Tab[] = ['brief', 'watch',   // comment with 'quote'
  'desk']
const COMMAND_PAGES: CommandPage[] = [
  { id: 'brief', code: 'BRF', label: 'Morning brief', hint: 'today\\'s market' },
  { id: 'watch', code: 'WTCH', label: 'Watch · monitor' },
  // { id: 'ghost', code: 'GHST', label: 'commented out' },
  { id: 'desk',  code: 'DESK', label: 'Decision [Desk]' },
]
  const tabList = [
    { id: 'brief', label: 'Brief' },
    { id: 'desk', label: 'Desk', badge: n || undefined },
  ]
"""


def test_parse_page_source_fixture():
    assert pages.parse_tab_ids(TSX) == ["brief", "watch", "desk"]
    cp = pages.parse_command_pages(TSX)
    assert [(p.id, p.code, p.label) for p in cp] == [("brief", "BRF", "Morning brief"), ("watch", "WTCH", "Watch · monitor"),
                                                    ("desk", "DESK", "Decision [Desk]")]
    assert cp[0].hint == "today's market"
    assert pages.parse_tab_strip(TSX) == ["brief", "desk"]


def test_parse_page_source_rejects_bad_shape():
    with pytest.raises(pages.PageSourceError):
        pages.parse_tab_ids("const OTHER = []")
    with pytest.raises(pages.PageSourceError):
        pages.parse_command_pages("const COMMAND_PAGES: CommandPage[] = [ { id: 'x', label: 'no code' } ]")
    with pytest.raises(pages.PageSourceError):
        pages.parse_tab_ids("const TAB_IDS: Tab[] = ['a', 'a']")


def test_real_page_tsx_has_43_consistent_pages():
    """43 since the gold program (reports/gold_program/PLAN.md Appendix A; B4A registers the GOLD page)."""
    src = pages.load_page_source()
    assert len(src.tab_ids) == 43 and len(src.command_pages) == 43, (len(src.tab_ids), len(src.command_pages))
    assert {p.id for p in src.command_pages} == set(src.tab_ids)
    assert len(src.tab_strip) >= 9


def test_parse_rust_pages_struct_and_tuple_forms():
    structs = '''pub struct Page { pub id: &'static str, pub code: &'static str }
    pub const PAGES: [Page; 2] = [
        Page { id: "brief", code: "BRF", label: "Morning brief", group: Group::Markets, shortcut: 1 },
        // Page { id: "ghost", code: "G", label: "x" },
        Page { id: "risk", code: "RSK", label: "Risk \\"dash\\"", group: Group::PortfolioRisk, shortcut: 0 },
    ];'''
    got = pages.parse_rust_pages(structs)
    assert [(p.id, p.code, p.label) for p in got] == [("brief", "BRF", "Morning brief"), ("risk", "RSK", 'Risk "dash"')]
    tuples = 'pub const PAGES: &[(&str, &str, &str, u8)] = &[("brief", "BRF", "Morning brief", 1), ("desk", "DESK", "Desk", 3)];'
    assert [p.id for p in pages.parse_rust_pages(tuples)] == ["brief", "desk"]
    with pytest.raises(pages.PageSourceError):
        pages.parse_rust_pages("fn main() {}")


# ── failure policy ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,status,failure,left,expect_fail,kind", [
    (f"{BASE}/api/desk/status", 500, None, False, True, "http"),
    (f"{BASE}/api/desk/status", 404, None, True, True, "http"),
    (f"{BASE}/api/telemetry/logs/stream", None, "net::ERR_ABORTED", True, False, "stream_abort_on_navigation"),
    (f"{BASE}/api/telemetry/logs/stream", None, "cancelled", True, False, "stream_abort_on_navigation"),
    (f"{BASE}/api/pipeline/ml-stream/job-1", None, "Load request cancelled", True, False, "stream_abort_on_navigation"),
    (f"{BASE}/api/telemetry/logs/stream", None, "net::ERR_ABORTED", False, True, "stream_abort_in_tab"),
    (f"{BASE}/api/telemetry/logs/stream", None, "net::ERR_CONNECTION_REFUSED", True, True, "network"),
    (f"{BASE}/api/desk/status", None, "net::ERR_ABORTED", True, True, "aborted_by_navigation"),
    (f"{BASE}/api/desk/status", None, "cancelled", False, True, "aborted_in_tab"),
    (f"{BASE}/api/telemetry/logs/streamX", None, "net::ERR_ABORTED", True, True, "aborted_by_navigation"),
    ("https://fonts.googleapis.com/css2?x", 403, None, False, False, "third_party_http"),
    ("https://s.tradingview.com/w.js", None, "net::ERR_FAILED", False, False, "third_party_network"),
])
def test_classify_request_failure(url, status, failure, left, expect_fail, kind):
    v = netpolicy.classify_request_failure(url=url, base_origin=BASE, status=status, failure_text=failure, left_tab=left)
    assert (v.failure, v.kind) == (expect_fail, kind)


def test_a_poll_started_after_the_drain_is_cut_by_the_harness_not_a_failure():
    """5 Nov: MOV's 2 s quote poll began between the drain's last check (nothing pending) and leave()."""
    url = f"{BASE}/api/live/quotes?symbols=TCS"
    v = netpolicy.classify_request_failure(url=url, base_origin=BASE, status=None, failure_text="net::ERR_ABORTED",
                                           left_tab=True, started_after_drain=True)
    assert (v.failure, v.kind) == (False, "poll_cut_at_leave")
    # negative controls: pending through the drain is still a failure; an HTTP error or a refused connection after
    # the drain is still a failure; an abort while the tab is open is still a failure
    assert netpolicy.classify_request_failure(url=url, base_origin=BASE, status=None, failure_text="net::ERR_ABORTED",
                                              left_tab=True, started_after_drain=False).kind == "aborted_by_navigation"
    assert netpolicy.classify_request_failure(url=url, base_origin=BASE, status=500, failure_text=None, left_tab=True,
                                              started_after_drain=True).failure is True
    assert netpolicy.classify_request_failure(url=url, base_origin=BASE, status=None, failure_text="net::ERR_CONNECTION_REFUSED",
                                              left_tab=True, started_after_drain=True).failure is True
    assert netpolicy.classify_request_failure(url=url, base_origin=BASE, status=None, failure_text="net::ERR_ABORTED",
                                              left_tab=False, started_after_drain=True).kind == "aborted_in_tab"


def test_stream_allowlist_is_exactly_six_paths():
    ok = ["/api/telemetry/logs/stream", "/api/pipeline/ml-stream/x", "/api/pipeline/rl-stream/x", "/api/ml/train/stream",
          "/api/analytics/backtest/stream", "/api/analytics/wfo-backtest/stream"]
    bad = ["/api/telemetry/logs", "/api/pipeline/ml-stream/x/y", "/api/ml/train", "/api/analytics/backtest/streamx",
           "/x/api/telemetry/logs/stream"]
    assert all(netpolicy.is_stream_path(p) for p in ok)
    assert not any(netpolicy.is_stream_path(p) for p in bad)


def test_endpoint_key_templates_live_values():
    k = netpolicy.endpoint_key
    assert k("get", f"{BASE}/api/stocks/TCS/detail?days=90&limit=5") == "GET /api/stocks/{sym}/detail?days,limit"
    assert k("GET", f"{BASE}/api/stocks/M%26M/ohlcv") == "GET /api/stocks/{sym}/ohlcv"
    assert k("GET", f"{BASE}/api/x/2026-10-24/123") == "GET /api/x/{date}/{n}"
    assert k("GET", f"{BASE}/api/pipeline/ml-stream/3f9a2b7c-11aa") == "GET /api/pipeline/ml-stream/{id}"
    assert k("POST", f"{BASE}/api/desk/status") == "POST /api/desk/status"
    assert k("GET", f"{BASE}/api/stocks/TCS/detail", template=False) == "GET /api/stocks/TCS/detail"
    assert netpolicy.status_class(204) == "2xx" and netpolicy.status_class(None, "stream_abort_on_navigation") == "ABORT"
    assert netpolicy.status_class(None, "network") == "ERR"


def test_normalize_text_masks_numbers_origins_assets():
    a = netpolicy.normalize_text("NIFTY 24,812.35 (+1.2%) at http://localhost:3000/_next/static/chunks/abc123.js 09:15")
    b = netpolicy.normalize_text("NIFTY 24,790.10 (-0.4%) at http://127.0.0.1:8092/_next/static/chunks/zz9.js 10:42")
    assert a == b
    assert netpolicy.normalize_text("  Holdings   ( 12 ) ") == "Holdings ( # )"
    assert netpolicy.normalize_text("took 250 ms, 3.5 cr, 12% up") == "took #, #, # up"
    assert netpolicy.normalize_text(None) == ""


def _visit(fp=None, **kw):
    v = {"url": f"{BASE}/?tab=desk", "error": None, "app_error": False, "skeleton_at_end": False,
         "timing": {"ready": True, "ready_ms": 500},
         "fingerprint": fp or {"title": "", "page_headers": ["DESK Decision Desk"], "panels": ["Book"], "headings": [],
                               "tables": 1, "table_headers": ["A | B"], "canvas": 0, "recharts": 1, "iframes": [],
                               "error_boxes": [], "skeleton": False}}
    v.update(kw)
    return v


def _events(**kw):
    e = {"console_errors": [], "console_warnings": [], "page_errors": [], "crashed": False, "failed_requests": [],
         "allowed_aborts": [], "third_party_failures": [], "websockets": [], "non_get_api": [],
         "api": {"GET /api/desk/status": {"count": 2, "statuses": ["2xx"], "paths": []}}}
    e.update(kw)
    return e


def test_failure_lines_default_and_strict():
    assert failure_lines(_visit(), _events(), strict=False) == []
    ev = _events(console_errors=["boom"], page_errors=["TypeError: x"], console_warnings=["warn"],
                 third_party_failures=[{"method": "GET", "url": "https://x", "reason": "HTTP 403"}],
                 failed_requests=[{"method": "GET", "url": f"{BASE}/api/a", "reason": "HTTP 500"}])
    lines = failure_lines(_visit(), ev, strict=False)
    assert {ln.split(":")[0] for ln in lines} == {"page_error", "console_error", "failed_request"}
    strict = failure_lines(_visit(fingerprint=None), ev, strict=True)
    assert any(ln.startswith("console_warning") for ln in strict) and any(ln.startswith("third_party") for ln in strict)
    assert failure_lines(_visit(skeleton_at_end=True), _events(), strict=False)[0].startswith("not_ready")
    assert failure_lines(_visit(timing={"ready": False}), _events(), strict=False)[0].startswith("not_ready")
    assert failure_lines(_visit(error="TimeoutError: x"), _events(), strict=False)[0].startswith("navigation")
    ws = _events(websockets=[{"url": "ws://localhost:3000/api/monitor/ws/monitor", "errors": ["reset"]}])
    assert failure_lines(_visit(), ws, strict=False)[0].startswith("websocket_error")


def test_normalize_fingerprint_masks_live_numbers():
    fp = normalize_fingerprint({"title": "DESK · 3", "page_headers": ["DESK NAV ₹12,34,567"], "panels": ["Holdings (20)"],
                                "headings": [], "table_headers": ["Qty | P&L 2.5%"], "error_boxes": ["▲ 503 down"],
                                "tables": 2, "canvas": 1})
    assert fp["panels"] == ["Holdings (#)"] and fp["tables"] == 2 and fp["error_boxes"] == ["▲ # down"]


# ── parity comparison ──────────────────────────────────────────────────────────────────────────────

def test_compare_identical_is_parity():
    assert parity.compare(_visit(), _events(), _visit(), _events())["reasons"] == []


def test_compare_detects_each_difference_class():
    fp_b = dict(_visit()["fingerprint"], panels=["Book", "Extra"], tables=2, recharts=0, error_boxes=["▲ #"])
    eb = _events(api={"GET /api/desk/status": {"count": 1, "statuses": ["5xx"], "paths": []},
                      "GET /api/new": {"count": 1, "statuses": ["2xx"], "paths": []}},
                 console_errors=["Failed to load resource: 500"])
    r = parity.compare(_visit(), _events(), _visit(fingerprint=fp_b), eb)
    text = " | ".join(r["reasons"])
    for needle in ("API request set", "status classes", "console errors", "panels", "tables", "recharts presence",
                   "error boxes"):
        assert needle in text, needle
    assert r["diff"]["api_only_b"] == ["GET /api/new"]


def test_compare_ignores_live_counts_and_order():
    ea = _events(api={"GET /api/a": {"count": 1, "statuses": ["2xx"], "paths": []},
                      "GET /api/b": {"count": 9, "statuses": ["2xx"], "paths": []}})
    eb = _events(api={"GET /api/b": {"count": 3, "statuses": ["2xx"], "paths": []},
                      "GET /api/a": {"count": 7, "statuses": ["2xx"], "paths": []}})
    fa = dict(_visit()["fingerprint"], panels=["X", "Y"], canvas=3)
    fb = dict(_visit()["fingerprint"], panels=["Y", "X"], canvas=1)
    assert parity.compare(_visit(fingerprint=fa), ea, _visit(fingerprint=fb), eb)["reasons"] == []


# ── streams ────────────────────────────────────────────────────────────────────────────────────────

def test_sse_parser_frames_and_heartbeats():
    p = streams.SSEParser()
    assert p.feed(b"event: status\ndata: {\"status\": \"pend") == []
    frames = p.feed(b"ing\"}\n\n: heartbeat\n\ndata: a\ndata: b\r\n\r\n")
    assert frames[0] == {"kind": "event", "event": "status", "data": '{"status": "pending"}'}
    assert frames[1] == {"kind": "comment", "comment": "heartbeat"}
    assert frames[2] == {"kind": "event", "event": "message", "data": "a\nb"}


# ── self-test contract ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("report,ok", [
    ({"ok": True, "checks": [{"name": "boot_paint", "ok": True}, {"name": "csp", "ok": True}]}, True),
    ({"ok": True, "checks": [{"name": "boot_paint", "ok": True}, {"name": "csp", "ok": False}]}, False),
    ({"checks": {"a": {"ok": True}, "b": True}}, True),
    ({"checks": {"a": {"status": "PASS"}}}, True),
    ({"ok": False, "checks": [{"name": "a", "ok": True}]}, False),
    ({"ok": True, "checks": []}, False),
    ("not an object", False),
])
def test_evaluate_selftest_shapes(report, ok):
    assert run_selftest.evaluate_selftest(report)[0] is ok


def test_last_json_object_after_log_lines():
    text = 'log {"not": json\n{"ok": true, "checks": [{"name": "x", "ok": true}]}\ntrailer'
    assert run_selftest.last_json_object(text)["ok"] is True
    assert run_selftest.last_json_object("no json") is None


def _fake_app(tmp_path: Path, identifier: str = run_selftest.IDENTIFIER, payload: int = 1000) -> Path:
    app = tmp_path / "SuryaDhana.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "suryadhana").write_bytes(b"\0" * payload)
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleIdentifier": identifier, "CFBundleExecutable": "suryadhana",
                       "CFBundleShortVersionString": "1.0.0"}, f)
    return app


def test_check_bundle_identity_and_size(tmp_path):
    c, info = run_selftest.check_bundle(_fake_app(tmp_path), max_mb=25)
    assert c.status == "PASS" and info["CFBundleExecutable"] == "suryadhana"
    c2, _ = run_selftest.check_bundle(_fake_app(tmp_path / "b", identifier="com.other"), max_mb=25)
    assert c2.status == "FAIL" and "identifier" in c2.detail
    c3, _ = run_selftest.check_bundle(_fake_app(tmp_path / "c", payload=2 * 1048576), max_mb=1)
    assert c3.status == "FAIL" and "MiB" in c3.detail


def test_launch_agent_state_filters_app_agents(tmp_path, monkeypatch):
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    app = _fake_app(tmp_path)
    exe = str((app / "Contents" / "MacOS" / "suryadhana").resolve())
    for name, pl in {
        "SuryaDhana.plist": {"Label": "SuryaDhana", "ProgramArguments": [exe], "RunAtLoad": True},
        "com.suryadhana.watchdog.plist": {"Label": "com.suryadhana.watchdog", "ProgramArguments": ["/bin/bash", "x.sh"]},
        "other.plist": {"Label": "com.other", "ProgramArguments": ["/Applications/Other.app/Contents/MacOS/o"]},
    }.items():
        with open(agents / name, "wb") as f:
            plistlib.dump(pl, f)
    monkeypatch.setattr(run_selftest, "LAUNCH_AGENTS", agents)
    state = run_selftest.launch_agent_state(app, "suryadhana")
    assert [a["label"] for a in state] == ["SuryaDhana"]
    assert state[0]["points_to_this_app"] and state[0]["run_at_load"]
    assert run_selftest.check_autostart(app, "suryadhana", "any").status == "PASS"
    assert run_selftest.check_autostart(app, "suryadhana", "off").status == "FAIL"


def test_find_app_missing_returns_none(tmp_path):
    assert run_selftest.find_app(str(tmp_path / "nope.app")) is None


# ── Tauri ACL resolver ─────────────────────────────────────────────────────────────────────────────

def _acl_tree(tmp_path: Path) -> Path:
    st = tmp_path / "src-tauri"
    (st / "gen" / "schemas").mkdir(parents=True)
    (st / "permissions").mkdir()
    (st / "build.rs").write_text('fn main() { tauri_build::try_build(tauri_build::Attributes::new().app_manifest('
                                 'tauri_build::AppManifest::new().commands(&["shell_info", "stack_stop"]))).unwrap(); }')
    (st / "permissions" / "remote.toml").write_text('[[set]]\nidentifier = "remote-shell"\npermissions = ["allow-shell-info"]\n')
    manifests = {"core:window": {"default_permission": {"permissions": ["allow-title"]}, "permission_sets": {},
                                 "permissions": {"allow-title": {"commands": {"allow": ["title"]}}}},
                 "core": {"default_permission": {"permissions": ["core:window:default"]}, "permission_sets": {}, "permissions": {}},
                 "fs": {"default_permission": None, "permission_sets": {},
                        "permissions": {"allow-read": {"commands": {"allow": ["read"]}}}}}
    (st / "gen" / "schemas" / "acl-manifests.json").write_text(json.dumps(manifests))
    return st


def test_acl_resolver(tmp_path):
    acl = tauri_acl.Acl.load(_acl_tree(tmp_path))
    assert acl.resolve("remote-shell") == {"shell_info"}
    assert acl.resolve("allow-stack-stop") == {"stack_stop"}
    assert acl.resolve("core:default") == {"plugin:window|title"}
    assert acl.resolve("fs:allow-read") == {"plugin:fs|read"}
    with pytest.raises(tauri_acl.AclError):
        acl.resolve("allow-unknown-cmd")
    with pytest.raises(tauri_acl.AclError):
        acl.resolve("nosuchplugin:default")
    assert tauri_acl.split_identifier("core:event:allow-listen") == ("core:event", "allow-listen")
    assert tauri_acl.permission_id({"identifier": "fs:allow-read", "allow": [{"path": "$HOME"}]}) == "fs:allow-read"


def test_acl_capabilities_and_handlers(tmp_path):
    st = _acl_tree(tmp_path)
    (st / "capabilities").mkdir()
    (st / "capabilities" / "remote.json").write_text(json.dumps(
        {"identifier": "remote", "remote": {"urls": ["http://127.0.0.1:8010/*"]}, "permissions": ["remote-shell"]}))
    (st / "src").mkdir()
    (st / "src" / "lib.rs").write_text("builder.invoke_handler(tauri::generate_handler![\n  shell::shell_info, // c\n  stack_stop,\n])")
    caps = tauri_acl.load_capabilities(st)
    assert len(caps) == 1 and tauri_acl.is_remote(caps[0])
    assert tauri_acl.app_manifest_commands(st) == ["shell_info", "stack_stop"]
    assert tauri_acl.registered_handlers(st) == ["shell_info", "stack_stop"]


def test_acl_runtime_capability_placeholders(tmp_path):
    st = _acl_tree(tmp_path)
    (st / "capabilities-runtime").mkdir()
    (st / "capabilities-runtime" / "remote.json").write_text(json.dumps(
        {"identifier": "rt", "local": False, "remote": {"urls": ["__UI_ORIGIN__", "__UI_ORIGIN_ALIAS__"]},
         "permissions": ["allow-shell-info"]}))
    caps = tauri_acl.load_capabilities(st)
    assert caps[0]["_file"] == "capabilities-runtime/remote.json"
    assert caps[0]["remote"]["urls"] == ["http://127.0.0.1:8010", "http://localhost:8010"]
    custom = tauri_acl.load_capabilities(st, {"__UI_ORIGIN_ALIAS__": "http://a", "__UI_ORIGIN__": "http://b"})
    assert custom[0]["remote"]["urls"] == ["http://b", "http://a"]


# ── scratch server (MockTransport backend) ─────────────────────────────────────────────────────────

@pytest.fixture()
def scratch(tmp_path):
    from fastapi.testclient import TestClient

    ui = tmp_path / "export"
    (ui / "_next" / "static" / "chunks").mkdir(parents=True)
    (ui / "index.html").write_text("<html>index</html>")
    (ui / "404.html").write_text("<html>nf</html>")
    js = b"console.log('x');" * 200
    (ui / "_next" / "static" / "chunks" / "a.js").write_bytes(js)
    (ui / "_next" / "static" / "chunks" / "a.js.gz").write_bytes(gzip.compress(js))
    (tmp_path / "secret.txt").write_text("outside")
    seen: list[httpx.Request] = []

    def backend(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/api/sse":   # stream= (not content=): the proxy streams like a real transport
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=httpx.ByteStream(b"data: 1\n\n"))
        body = json.dumps({"path": req.url.path, "q": dict(req.url.params)}).encode()
        return httpx.Response(418 if req.url.path == "/api/teapot" else 200, headers={"content-type": "application/json"},
                              stream=httpx.ByteStream(body))

    client = httpx.AsyncClient(transport=httpx.MockTransport(backend), base_url="http://backend")
    app = scratch_server.create_app(ui, "http://backend", client=client,
                                    inject=scratch_server.parse_inject([r"^/api/broken$=503"]))
    return TestClient(app), seen, js


def test_scratch_static_serving(scratch):
    c, _, js = scratch
    r = c.get("/")
    assert r.status_code == 200 and r.text == "<html>index</html>" and r.headers["cache-control"] == "no-cache"
    r = c.get("/_next/static/chunks/a.js", headers={"accept-encoding": "gzip"})
    assert r.status_code == 200 and r.content == js and "immutable" in r.headers["cache-control"]
    assert r.headers.get("content-encoding") == "gzip"
    r = c.get("/missing/page")
    assert r.status_code == 404 and "nf" in r.text
    assert c.get("/../secret.txt").status_code == 404
    assert c.get("/__qa/health").json()["status"] == "ok"


def test_scratch_api_forwarding(scratch):
    c, seen, _ = scratch
    r = c.get("/api/stocks/list?limit=5&skip=0")
    assert r.status_code == 200 and r.json() == {"path": "/api/stocks/list", "q": {"limit": "5", "skip": "0"}}
    assert c.get("/api/teapot").status_code == 418
    r = c.get("/api/sse")
    assert r.headers["content-type"].startswith("text/event-stream") and r.text == "data: 1\n\n"
    assert c.get("/health").status_code == 200 and seen[-1].url.path == "/health"
    n = len(seen)
    r = c.get("/api/broken")
    assert r.status_code == 503 and "injected" in r.text and len(seen) == n   # never reached the backend


def test_scratch_block_mutations(tmp_path):
    from fastapi.testclient import TestClient

    (tmp_path / "index.html").write_text("x")
    called = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: called.append(r) or httpx.Response(200, stream=httpx.ByteStream(b"{}"))), base_url="http://backend")
    c = TestClient(scratch_server.create_app(tmp_path, "http://backend", client=client, block_mutations=True))
    assert c.post("/api/desk/run", json={}).status_code == 403 and not called
    assert c.get("/api/desk/status").status_code == 200 and len(called) == 1
    with pytest.raises(ValueError):
        scratch_server.parse_inject(["no-status"])


# ── R-OPS-08 / R-OPS-09: the live backend gets neither writes nor relayed WebSockets by default ─────────────

@pytest.mark.parametrize("url,live", [
    ("http://127.0.0.1:8010", True), ("http://localhost:8010/", True), ("http://[::1]:8010", True),
    ("http://0.0.0.0:8010", True), ("not a url ::", True),
    ("http://127.0.0.1:8095", False), ("http://backend", False), ("http://127.0.0.1:18971", False),
])
def test_is_live_backend(url, live):
    assert scratch_server.is_live_backend(url) is live


@pytest.mark.parametrize("backend,flags,want", [
    ("http://127.0.0.1:8010", {}, (True, False)),                              # the default: safe
    ("http://127.0.0.1:8010", {"allow_mutations": True}, (False, False)),
    ("http://127.0.0.1:8010", {"allow_live_ws": True}, (True, True)),
    ("http://127.0.0.1:8099", {}, (False, True)),                              # a scratch ui-api: relayed
    ("http://127.0.0.1:8099", {"block_mutations": True}, (True, True)),
])
def test_resolve_policy(backend, flags, want):
    assert scratch_server.resolve_policy(backend, **flags) == want


def test_resolve_policy_refuses_contradicting_flags(tmp_path):
    with pytest.raises(ValueError):
        scratch_server.resolve_policy("http://127.0.0.1:8010", block_mutations=True, allow_mutations=True)
    (tmp_path / "index.html").write_text("x")
    assert scratch_server.main(["--ui", str(tmp_path), "--block-mutations", "--allow-mutations"]) == 2


def test_cli_default_against_the_live_backend_blocks_writes_and_the_ws_relay(tmp_path, monkeypatch):
    """Negative control for R-OPS-08: before, the default flags relayed a page's same-origin write to the live
    ui-api, whose guard admitted it (test_scratch_proxy_same_origin_write_reaches_the_guarded_backend)."""
    built: dict = {}
    monkeypatch.setattr(scratch_server, "create_app", lambda *a, **k: built.update(k) or object())
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    (tmp_path / "index.html").write_text("x")
    assert scratch_server.main(["--ui", str(tmp_path)]) == 0
    assert built["block_mutations"] is True and built["relay_ws"] is False
    assert scratch_server.main(["--ui", str(tmp_path), "--allow-mutations", "--allow-live-ws"]) == 0
    assert built["block_mutations"] is False and built["relay_ws"] is True


def test_without_the_ws_relay_a_page_socket_is_accepted_then_closed_and_never_reaches_the_backend(tmp_path):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    (tmp_path / "index.html").write_text("x")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)), base_url="http://backend")
    app = scratch_server.create_app(tmp_path, "http://127.0.0.1:8010", client=client, ws_backend="ws://127.0.0.1:9",
                                    block_mutations=True, relay_ws=False)
    c = TestClient(app)
    with c.websocket_connect("/api/monitor/ws/monitor") as ws, pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_text()
    assert closed.value.code == 1008 and "--allow-live-ws" in closed.value.reason
    health = c.get("/__qa/health").json()
    assert health["mutations"] == "blocked" and health["websockets"] == "closed"
    assert c.post("/api/desk/run", json={}).status_code == 403


def test_scratch_server_doc_no_longer_claims_read_only_by_construction():
    doc = scratch_server.__doc__ or ""
    assert "Read-only by construction" not in doc and "is NOT read-only by construction" in doc
    assert "--allow-mutations" in doc and "--allow-live-ws" in doc


# ── ui_audit CLI helpers ───────────────────────────────────────────────────────────────────────────

def test_ui_audit_cli_is_backward_compatible():
    args = ui_audit.build_parser().parse_args([])
    assert args.base == "http://127.0.0.1:8010" and args.wait == 6.0 and args.browser == "chromium"
    assert args.tabs == ",".join(ui_audit.TABS) and len(ui_audit.TABS) == 16   # 15 + gold (gold program T10)
    assert ui_audit.TABS["gold"] == "Gold terminal"
    assert ui_audit.resolve_tabs("desk, stocks", []) == ["desk", "stocks"]
    assert ui_audit.resolve_tabs("all", ["a", "b"]) == ["a", "b"]
    for b in ("chromium", "webkit", "both"):
        assert ui_audit.build_parser().parse_args(["--browser", b, "--strict"]).strict


def test_ui_audit_summary_and_markdown():
    tabs = {"desk": {"pass": True, "timing": {"ready_ms": 500, "idle_ms": None, "total_ms": 7000}, "console_errors": [],
                     "page_errors": [], "failed_requests": [], "allowed_aborts": [1], "third_party_failures": [],
                     "failures": [], "code": "DESK", "nav_timing": {"fcp_ms": 30}},
            "sys": {"pass": False, "timing": {"ready_ms": 900, "idle_ms": 800, "total_ms": 8000}, "console_errors": ["x"],
                    "page_errors": [], "failed_requests": [], "allowed_aborts": [], "third_party_failures": [],
                    "failures": ["console_error: x|y"], "code": "SYS", "nav_timing": None}}
    s = ui_audit.summarize(tabs)
    assert s["passed"] == 1 and s["failed"] == ["sys"] and s["allowed_aborts"] == 1 and s["ready_ms_max"] == 900
    md = ui_audit.render_markdown({"meta": {"base": BASE, "started_at": "t0", "finished_at": "t1", "strict": False,
                                            "wait_s": 6, "label": ""},
                                   "engines": {"webkit": {"browser_version": "26", "summary": s, "tabs": tabs}},
                                   "ok": False})
    assert "**FAIL**" in md and "console_error: x\\|y" in md and md.rstrip().endswith("**Overall: FAIL**")
    assert re.search(r"\| desk \| DESK \| PASS \| 500 \| — \|", md)


# ── platform seams (PLAN §5 probes whose routing depends on the front server) ─────────────────────

@pytest.mark.parametrize("value,seam", [
    ("/health", True), ("GET /api/health", True), ("/version", True), ("/build-info.json", True),
    ("GET /api/prefs", True), ("http://127.0.0.1:8010/api/prefs/suryadhana.watchlist.v1", True),
    ("GET /api/healthz", False), ("GET /api/prefs/a/b", False), ("/api/desk/status", False), ("GET /api/version", False),
])
def test_platform_seam_paths_are_narrow(value, seam):
    assert netpolicy.is_platform_seam(value) is seam


def _seam_404_events(base: str = BASE):
    url = f"{base}/api/health"
    return _events(api={"GET /api/desk/status": {"count": 2, "statuses": ["2xx"], "paths": []},
                        "GET /api/health": {"count": 3, "statuses": ["4xx"], "paths": []}},
                   console_errors=["Failed to load resource: the server responded with a status of 404 (Not Found)"],
                   console_detail=[{"text": "Failed to load resource: the server responded with a status of 404 (Not Found)",
                                    "url": url, "seam": True}],
                   failed_requests=[{"method": "GET", "url": url, "status": 404, "reason": "HTTP 404", "seam": True}])


def test_compare_sets_platform_seams_aside_but_reports_them():
    ea, eb = _seam_404_events(), _events(console_detail=[])
    r = parity.compare(_visit(), ea, _visit(), eb)
    assert r["reasons"] == [] and r["diff"]["platform_seams"]["a"]["api"] == {"GET /api/health": ["4xx"]}
    assert r["notes"] and "platform seams differ" in r["notes"][0]
    strict = parity.compare(_visit(), ea, _visit(), eb, seams=False)
    text = " | ".join(strict["reasons"])
    assert "API request set differs" in text and "console errors differ" in text


def test_compare_seam_exclusion_keeps_non_seam_console_errors():
    ea = _seam_404_events()
    ea["console_detail"].append({"text": "TypeError: boom", "url": f"{BASE}/_next/static/x.js", "seam": False})
    ea["console_errors"].append("TypeError: boom")
    r = parity.compare(_visit(), ea, _visit(), _events(console_detail=[]))
    assert any("console errors differ" in x and "TypeError" in x for x in r["reasons"])


def test_non_seam_failures():
    from desktop_qa.probe import non_seam_failures

    ev = _seam_404_events()
    lines = failure_lines(_visit(), ev, strict=False)
    assert len(lines) == 2 and non_seam_failures(lines, ev["failed_requests"], ev["console_detail"]) == []
    # the same generic console text also produced by a NON-seam URL keeps the console line
    ev["console_detail"].append({"text": ev["console_detail"][0]["text"], "url": f"{BASE}/api/desk/x", "seam": False})
    ev["failed_requests"].append({"method": "GET", "url": f"{BASE}/api/desk/x", "status": 404, "reason": "HTTP 404"})
    lines = failure_lines(_visit(), ev, strict=False)
    left = non_seam_failures(lines, ev["failed_requests"], ev["console_detail"])
    assert any(x.startswith("console_error") for x in left) and any("/api/desk/x" in x for x in left)
    assert not any("/api/health" in x for x in left)


def test_ui_audit_failed_endpoints_breakdown():
    f = {"method": "GET", "url": f"{BASE}/api/health", "status": 404, "reason": "HTTP 404", "seam": True}
    g = {"method": "GET", "url": f"{BASE}/api/stocks/TCS/detail?days=5", "status": 500, "reason": "HTTP 500"}
    rows = ui_audit.failed_endpoints({"a": {"failed_requests": [f, f]}, "b": {"failed_requests": [f, g]}})
    assert rows[0] == {"endpoint": "GET /api/health → HTTP 404", "platform_seam": True, "tab_ids": ["a", "b"], "tabs": 2}
    assert rows[1]["endpoint"] == "GET /api/stocks/{sym}/detail?days → HTTP 500" and rows[1]["platform_seam"] is False


def test_parity_cli_defaults():
    a = parity.build_parser().parse_args(["--b", "http://127.0.0.1:8010", "--out", "x"])
    assert a.seams is True and a.observe == 12.0 and a.browser == "both" and a.retries == 1
    assert parity.build_parser().parse_args(["--b", "x", "--out", "y", "--no-seam-exclusion"]).seams is False


# ── streams: content-encoded event streams are caught ──────────────────────────────────────────────

def test_body_decoder_incremental_gzip_and_encoding_problem():
    import zlib

    payload = b"event: status\ndata: {}\n\n: heartbeat\n\n"
    co = zlib.compressobj(9, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    wire = co.compress(payload) + co.flush()
    d = streams.BodyDecoder("gzip")
    out = b"".join(d.feed(wire[i:i + 7]) for i in range(0, len(wire), 7))
    assert out == payload and streams.BodyDecoder("identity").feed(b"x") == b"x"
    assert streams.BodyDecoder("br").supported is False
    assert streams.encoding_problem(None) is None and streams.encoding_problem("identity") is None
    assert "content-encoded (gzip)" in streams.encoding_problem("gzip")


def test_read_stream_flags_gzip_buffered_sse():
    import asyncio
    import zlib

    co = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    header_only = co.compress(b"event: status\ndata: {\"status\": \"pending\"}\n\n")   # held in the compressor

    async def run():
        def backend(req: httpx.Request) -> httpx.Response:
            assert "gzip" in req.headers["accept-encoding"]
            return httpx.Response(200, headers={"content-type": "text/event-stream", "content-encoding": "gzip"},
                                  stream=httpx.ByteStream(header_only))
        async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as c:
            return await streams.check_unknown_job_stream(c, "http://127.0.0.1:8010", "ml", release_wait_s=0)

    r = asyncio.run(run())
    assert r["status"] == "FAIL" and r["content_encoding"] == "gzip" and r["first_byte_ms"] is None
    assert any("content-encoded (gzip)" in p for p in r["problems"])
    assert r["outcome"].startswith("HTTP 200 but no SSE frame decoded")


def test_read_stream_pending_stream_passes():
    import asyncio

    async def run():
        def backend(req: httpx.Request) -> httpx.Response:
            body = b'event: status\ndata: {"status": "pending", "progress": 0}\n\n: heartbeat\n\n'
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=httpx.ByteStream(body))
        async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as c:
            return await streams.check_unknown_job_stream(c, "http://127.0.0.1:8010", "rl", release_wait_s=0)

    r = asyncio.run(run())
    assert r["status"] == "PASS", r["problems"]
    assert r["outcome"].startswith("pending stream") and r["first_heartbeat_ms"] is not None


# ── self-test: D2's report shape ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("report,ok", [
    ({"passed": True, "checks": [{"name": "boot_paint", "ok": True, "detail": "", "ms": 120.0}], "meta": {}}, True),
    ({"passed": False, "checks": [{"name": "boot_paint", "ok": True, "detail": "", "ms": 1.0}], "meta": {}}, False),
    ({"passed": True, "checks": [{"name": "csp", "ok": False, "detail": "x", "ms": None}], "meta": {}}, False),
])
def test_evaluate_selftest_d2_shape(report, ok):
    assert run_selftest.evaluate_selftest(report)[0] is ok


def test_selftest_live_launch_disables_first_run_autostart():
    src = Path(run_selftest.__file__).read_text()
    assert '"SURYADHANA_NO_AUTOSTART": "1"' in src and "--allow-autostart-change" in src
    launcher = run_selftest.Launcher(Path("/nonexistent/exe"), env={"SURYADHANA_NO_AUTOSTART": "1"})
    assert launcher.env["SURYADHANA_NO_AUTOSTART"] == "1" and "PATH" in launcher.env
    assert launcher.procs == []


def test_drain_ignores_responses_the_page_never_reads():
    import time as _t

    from desktop_qa.probe import TabProbe, _Req

    class _Page:
        def on(self, *_a):
            pass

    p = TabProbe(_Page(), BASE)
    now = _t.perf_counter()
    p.reqs = {1: _Req(1, "GET", f"{BASE}/api/a", "fetch", now),                                         # no response yet
              2: _Req(1, "GET", f"{BASE}/health", "fetch", now - 9, status=404, t_response=now - 8),   # body never read
              3: _Req(1, "GET", f"{BASE}/api/b", "fetch", now, status=200, t_response=now),             # body arriving
              4: _Req(1, "GET", f"{BASE}/api/telemetry/logs/stream", "eventsource", now),               # stream
              5: _Req(1, "GET", f"{BASE}/api/c", "fetch", now, done=True),                              # finished
              6: _Req(2, "GET", f"{BASE}/api/d", "fetch", now)}                                         # other tab
    assert sorted(p.pending_api(1)) == [f"{BASE}/api/a", f"{BASE}/api/b"]


def test_launcher_cleanup_reaps_its_children():
    """A terminated child must be reaped (a zombie looked like a stray instance to the old sweep)."""
    launcher = run_selftest.Launcher(Path("/bin/sleep"))
    p = launcher.start("30")
    assert p.poll() is None
    killed = launcher.cleanup()
    assert p.pid in killed and p.poll() is not None          # terminated AND reaped
    assert run_selftest._alive(p.pid) is False and run_selftest._terminate(p.pid) is False


def test_prefs_mode_script_pins_readonly_by_default_and_rejects_unknown():
    """Audits against the live ui-api must never write the owner's /api/prefs (D3 notes_for_pm)."""
    from desktop_qa import probe

    js = probe.prefs_mode_script("readonly")
    assert js is not None and "'suryadhana.prefs.mode'" in js and "'readonly'" in js and js.startswith("try")
    assert "'off'" in (probe.prefs_mode_script("off") or "")
    assert probe.prefs_mode_script("sync") is None
    with pytest.raises(ValueError):
        probe.prefs_mode_script("bogus")
    import ui_audit
    from desktop_qa import parity

    assert ui_audit.build_parser().parse_args([]).prefs_mode == "readonly"
    assert parity.build_parser().parse_args(["--b", "http://127.0.0.1:8010", "--out", "x"]).prefs_mode == "readonly"


def test_new_qa_context_installs_the_init_script_only_when_needed():
    from desktop_qa import probe

    class Ctx:
        def __init__(self) -> None:
            self.scripts: list[str] = []
            self.ws_routes: list = []

        def add_init_script(self, s: str) -> None:
            self.scripts.append(s)

        def route_web_socket(self, url, handler) -> None:
            self.ws_routes.append((url, handler))

    class Browser:
        def __init__(self) -> None:
            self.kwargs: dict = {}

        def new_context(self, **kw):
            self.kwargs = kw
            return Ctx()

    b = Browser()
    ctx = probe.new_qa_context(b, viewport={"width": 10, "height": 10})
    assert b.kwargs == {"viewport": {"width": 10, "height": 10}} and len(ctx.scripts) == 1
    assert probe.new_qa_context(Browser(), prefs_mode="sync").scripts == []
    # R-OPS-09: every WebSocket mocked by default (one catch-all route whose handler never connects to a server)
    ((url, _handler),) = ctx.ws_routes
    assert url.pattern == ".*" and url.match("ws://127.0.0.1:8010/api/monitor/ws/monitor")
    seen: list[str] = []
    ctx2 = probe.new_qa_context(Browser(), ws_mocked=seen)

    class WsRoute:
        url = "ws://127.0.0.1:8010/api/monitor/ws/monitor"

        def connect_to_server(self) -> None:  # pragma: no cover - must never be called
            raise AssertionError("a mocked socket never reaches a server")

    ctx2.ws_routes[0][1](WsRoute())
    assert seen == ["ws://127.0.0.1:8010/api/monitor/ws/monitor"]
    assert probe.new_qa_context(Browser(), live_websockets=True).ws_routes == [], "the explicit opt-out"


def test_qa_tools_never_pass_websockets_through_by_default():
    """The callers rely on new_qa_context's default; parity's opt-out is an explicit flag."""
    assert parity.build_parser().parse_args(["--b", "x", "--out", "y"]).live_websockets is False
    assert parity.build_parser().parse_args(["--b", "x", "--out", "y", "--live-websockets"]).live_websockets is True
    src = (ROOT / "scripts" / "desktop_qa" / "e2e_compare.py").read_text()
    assert "route_web_socket" not in src and "ws_mocked=mocked" in src


# ── expected program deltas (FX-UI adversarial check: the header's holiday lookup) ──────────────────────────

HOLIDAYS = "http://127.0.0.1:8010/api/market/eco-calendar?back=0&ahead=10"


def test_expected_delta_matches_method_path_and_exact_query_values():
    assert netpolicy.expected_delta("GET", HOLIDAYS) == "header-holidays"
    assert netpolicy.expected_delta("get", "/api/market/eco-calendar?ahead=10&back=0") == "header-holidays"  # order-free
    assert netpolicy.expected_delta("GET", "/api/market/eco-calendar?back=0&ahead=7") == "header-holidays"   # wave 2
    for method, url in (("GET", "/api/market/eco-calendar?back=7&ahead=30"),    # the ECO page's own calls
                        ("GET", "/api/market/eco-calendar?back=0&ahead=10&x=1"),
                        ("GET", "/api/market/eco-calendar"),
                        ("POST", HOLIDAYS),
                        ("GET", "/api/market/eco-calendarx?back=0&ahead=10")):
        assert netpolicy.expected_delta(method, url) is None, (method, url)


def test_netpolicy_knows_the_query_the_ui_actually_sends():
    """Drift guard: the expected delta is exactly what ui/components/desktop/holidays.ts fetches today (the shared
    ECO_SHARED_QUERY of ui/lib/api.ts, or a HOLIDAYS_URL literal as in round-1 releases)."""
    src = (ROOT / "ui" / "components" / "desktop" / "holidays.ts").read_text()
    literal = re.search(r"export const HOLIDAYS_URL = '([^']+)'", src)
    if literal:
        url = literal.group(1)
    else:
        assert "ECO_SHARED_QUERY" in src, "holidays.ts fetches holidays some new way: update netpolicy.EXPECTED_DELTAS"
        api = (ROOT / "ui" / "lib" / "api.ts").read_text()
        m = re.search(r"export const ECO_SHARED_QUERY = \{ back: (\d+), ahead: (\d+) \}", api)
        assert m, "ui/lib/api.ts ECO_SHARED_QUERY changed shape: update netpolicy.EXPECTED_DELTAS"
        assert re.search(r"client\.get<EcoCalendarResponse>\('/api/market/eco-calendar', \{ params: \{ back, ahead \} \}\)", api)
        url = f"/api/market/eco-calendar?back={m.group(1)}&ahead={m.group(2)}"
    assert netpolicy.expected_delta("GET", url) == "header-holidays", url


def _api(entries: dict) -> dict:
    return {"GET /api/desk/status": {"count": 2, "statuses": ["2xx"], "paths": []}, **entries}


def test_compare_sets_a_one_sided_expected_delta_aside_and_reports_it():
    key = "GET /api/market/eco-calendar?ahead,back"
    eb = _events(api=_api({key: {"count": 1, "statuses": ["2xx"], "paths": [key], "expected_delta": "header-holidays"}}))
    r = parity.compare(_visit(), _events(), _visit(), eb)
    assert r["reasons"] == [] and r["diff"]["expected_deltas"] == {"a_only": {}, "b_only": {key: "header-holidays"}}
    assert any("expected program deltas set aside" in n for n in r["notes"])
    strict = parity.compare(_visit(), _events(), _visit(), eb, expected=False)
    assert any("API request set differs" in x for x in strict["reasons"])
    # an endpoint that ALSO carried other calls (the ECO page's own) is compared as usual
    eb2 = _events(api=_api({key: {"count": 2, "statuses": ["2xx"], "paths": [key]}}))
    assert any("API request set differs" in x for x in parity.compare(_visit(), _events(), _visit(), eb2)["reasons"])


def test_summarize_marks_an_endpoint_expected_only_when_every_call_is():
    from desktop_qa.probe import TabProbe, _Req

    class Page:
        def on(self, *_a):
            pass

    p = TabProbe(Page(), "http://127.0.0.1:8010")
    p.reqs = {1: _Req(1, "GET", HOLIDAYS, "fetch", 0.0, status=200),
              2: _Req(2, "GET", HOLIDAYS, "fetch", 0.0, status=200),
              3: _Req(2, "GET", "http://127.0.0.1:8010/api/market/eco-calendar?back=7&ahead=30", "fetch", 0.0, status=200)}
    key = "GET /api/market/eco-calendar?ahead,back"
    assert p.summarize(1)["api"][key]["expected_delta"] == "header-holidays"
    assert "expected_delta" not in p.summarize(2)["api"][key]


def test_parity_cli_has_the_expected_delta_switch():
    ap = parity.build_parser()
    assert ap.parse_args(["--b", "x", "--out", "y"]).expected is True
    assert ap.parse_args(["--b", "x", "--out", "y", "--no-expected-deltas"]).expected is False


# ── gold program deltas (reports/gold_program/PLAN.md §b, §g, §h T12): NEW page, structure, /api/gold/* ──────────

def test_gold_expected_deltas_are_page_exact_and_tab_scoped():
    """Wave 1b (B6 adversarial major): each gold delta names its pages and the exact request the page sends."""
    d = netpolicy.expected_delta
    # BRF / WEI: the one gold line, window=W exactly
    assert d("GET", "/api/gold/health?window=W") == "gold-health-line"
    assert d("GET", "http://127.0.0.1:8010/api/gold/health?window=W", "brief") == "gold-health-line"
    assert d("GET", "/api/gold/health?window=W", "world") == "gold-health-line"
    assert d("GET", "/api/gold/health?window=W", "desk") is None                        # not declared for DESK
    assert d("GET", "/api/gold/health?window=D", "brief") is None                        # another window: the GOLD page's
    assert d("GET", "/api/gold/health", "brief") is None
    # MCXG: the shared selector, exchange=MCX exactly; the specs card A-only, no query
    assert d("GET", "/api/gold/contracts?exchange=MCX", "mcxgold") == "gold-mcxg-selector"
    assert d("GET", "/api/gold/contracts?exchange=COMEX", "mcxgold") is None             # the GOLD page's spec card read
    assert d("GET", "/api/gold/contracts?exchange=MCX", "commodity") is None
    assert d("GET", "/api/mcx/specs") == "gold-mcxg-specs-replaced" and d("GET", "/api/mcx/specs", "mcxgold") == "gold-mcxg-specs-replaced"
    assert d("GET", "/api/mcx/specs?x=1") is None and d("GET", "/api/mcx/specs", "brief") is None
    assert d("GET", "/api/mcx/quote?contract=GOLD") is None and d("POST", "/api/mcx/ticket") is None   # on both sides
    # CMDT / BRF: the retired desk's reads are A-only, any query (its saved inputs), the log ?threshold=300
    assert d("GET", "/api/commodity/gold-preopen?baseline=1", "commodity") == "gold-preopen-moved"
    assert d("GET", "/api/commodity/gold-preopen", "brief") == "gold-preopen-moved"
    assert d("GET", "/api/commodity/gold-preopen/log?threshold=300", "brief") == "gold-preopen-moved"
    assert d("GET", "/api/commodity/gold-preopen", "world") is None
    assert d("POST", "/api/commodity/gold-preopen/actual") is None and d("GET", "/api/commodity/overview") is None
    # BRKR: the TOTP status on load, no query; ?reveal=1 is a click, never on load
    assert d("GET", "/api/positions/totp/status", "broker") == "gold-brkr-totp-status"
    assert d("GET", "/api/positions/totp/status?reveal=1") is None and d("GET", "/api/positions/totp") is None
    assert d("GET", "/api/positions/totp/status", "gold") is None
    # the GOLD page: the whole family, any query — and only there
    for url in ("/api/gold", "/api/gold/health?window=D", "/api/gold/cot?weeks=52&report=disagg", "/api/gold/learn/tooltips",
                "/api/gold/contracts?exchange=COMEX"):
        assert d("GET", url, "gold") == "gold-page-api", url
        assert d("GET", url) == "gold-page-api", url              # page-free tagging (the probe): the tab check is PARITY's
        assert d("GET", url, "brief") is None, url
    assert d("GET", "/api/goldx/health") is None and d("POST", "/api/gold/snapshot") is None
    # the page-exact shapes come first, the family last; page-free tagging never yields the family for a page shape
    assert [x.id for x in netpolicy.EXPECTED_DELTAS].index("gold-health-line") < [x.id for x in netpolicy.EXPECTED_DELTAS].index("gold-page-api")
    # the exact-query page-free deltas are untouched
    assert d("GET", HOLIDAYS) == "header-holidays" and d("GET", HOLIDAYS, "desk") == "header-holidays"
    assert d("GET", "/api/market/eco-calendar?back=7&ahead=30") is None


def test_expected_delta_applies_is_the_tab_gate():
    a = netpolicy.expected_delta_applies
    assert a("header-holidays", "desk") and a("header-holidays", None)                  # page-free: everywhere
    assert a("gold-health-line", "brief") and a("gold-health-line", "world")
    assert not a("gold-health-line", "desk") and not a("gold-health-line", None)        # unknown tab: compared, not excused
    assert not a("gold-page-api", "brief") and a("gold-page-api", "gold")
    assert not a(None, "brief") and not a("no-such-delta", "brief")
    scoped = {x.id: x.tabs for x in netpolicy.EXPECTED_DELTAS if x.id.startswith("gold-")}
    assert scoped == {"gold-health-line": {"brief", "world"}, "gold-mcxg-selector": {"mcxgold"},
                      "gold-preopen-moved": {"commodity", "brief"}, "gold-mcxg-specs-replaced": {"mcxgold"},
                      "gold-brkr-totp-status": {"broker"}, "gold-page-api": {"gold"}}
    assert "commodity" not in scoped["gold-health-line"], "CMDT sends no gold read on B (chips only)"


def test_compare_keeps_a_gold_read_on_an_undeclared_page_as_a_diff():
    """Negative control for PLAN 0.1 #7: the same B-only tagged request is set aside on WEI and a DIFF on DESK."""
    key = "GET /api/gold/health?window"
    eb = _events(api=_api({key: {"count": 1, "statuses": ["2xx"], "paths": [key], "expected_delta": "gold-health-line"}}))
    ok = parity.compare(_visit(tab="world"), _events(), _visit(tab="world"), eb)
    assert ok["reasons"] == [] and ok["diff"]["expected_deltas"] == {"a_only": {}, "b_only": {key: "gold-health-line"}}
    bad = parity.compare(_visit(tab="desk"), _events(), _visit(tab="desk"), eb)
    assert bad["reasons"] == [f"API request set differs: only A [], only B ['{key}']"] and "expected_deltas" not in bad["diff"]
    assert bad["diff"]["api_only_b"] == [key]
    # a visit without a tab is compared too (an explicit tab= wins over the visits')
    assert parity.compare(_visit(), _events(), _visit(), eb)["reasons"] and \
        parity.compare(_visit(), _events(), _visit(), eb, tab="brief")["reasons"] == []
    # a family-tagged read (another window) on BRF is drift as well; the A-only retired desk read is excused on BRF only
    key2 = "GET /api/gold/cot?report,weeks"
    eb2 = _events(api=_api({key2: {"count": 1, "statuses": ["2xx"], "paths": [key2], "expected_delta": "gold-page-api"}}))
    assert parity.compare(_visit(tab="brief"), _events(), _visit(tab="brief"), eb2)["reasons"]
    key3 = "GET /api/commodity/gold-preopen"
    ea3 = _events(api=_api({key3: {"count": 1, "statuses": ["2xx"], "paths": [key3], "expected_delta": "gold-preopen-moved"}}))
    assert parity.compare(_visit(tab="brief"), ea3, _visit(tab="brief"), _events())["reasons"] == []
    assert parity.compare(_visit(tab="world"), ea3, _visit(tab="world"), _events())["reasons"]


def test_gold_deltas_are_what_the_ui_sends_and_the_server_mounts():
    """Drift guard (wave 1b): each declaration is read back from the fetchers (B4A/B4B) and the routes (B3) in the tree."""
    ui, api = ROOT / "ui", ROOT / "services" / "ui-api"
    gold_api = (ui / "lib" / "gold" / "api.ts").read_text()
    assert "export const GOLD_API = '/api/gold'" in gold_api
    assert re.search(r"health: `\$\{GOLD_API\}/health`", gold_api) and re.search(r"contracts: `\$\{GOLD_API\}/contracts`", gold_api)
    assert re.search(r"getGoldHealth = \(window: Window = 'D'\) =>\s*client\.get<GoldHealth>\(GOLD_ENDPOINTS\.health, \{ params: \{ window \} \}\)", gold_api)
    assert re.search(r"getGoldContracts = \(exchange = 'MCX'\) =>\s*client\.get<GoldContracts>\(GOLD_ENDPOINTS\.contracts, \{ params: \{ exchange \} \}\)", gold_api)
    for comp in ("Brief.tsx", "WorldMarkets.tsx"):                       # the one line: window W, nothing else gold
        src = (ui / "components" / comp).read_text()
        assert src.count("getGoldHealth('W')") == 1 and len(re.findall(r"\bgetGold\w*\(", src)) == 1, comp
    cmdt = (ui / "components" / "CommodityTab.tsx").read_text()
    assert not re.search(r"\bgetGold\w*\(|/api/gold", cmdt), "CMDT reads nothing gold on B: add a delta if that changes"
    mcxg = (ui / "components" / "McxGoldDesk.tsx").read_text()
    assert "getGoldContracts(sel.exchange)" in mcxg and len(re.findall(r"\bgetGold\w*\(", mcxg)) == 1
    assert "/api/mcx/specs" not in mcxg, "MCXG still reads the specs card: gold-mcxg-specs-replaced says A-only"
    sel = (ui / "components" / "gold" / "ContractsView.tsx").read_text()
    enabled = [m.group(1) for m in re.finditer(r"\{ value: '([A-Z]+)', label: '[^']*'(?!, disabled)", sel)]
    assert enabled == ["MCX"], f"the selector offers {enabled}: gold-mcxg-selector accepts exchange=MCX only"
    assert "export const DEFAULT_SEL: GoldContractSel = Object.freeze({ exchange: 'MCX'" in (ui / "lib" / "gold" / "prefs.ts").read_text()
    totp = (ui / "components" / "gold" / "IciciTotpPanel.tsx").read_text()
    assert "const TOTP_URL = '/api/positions/totp'" in totp
    assert "http.get<TotpStatus>(`${TOTP_URL}/status`, { params: reveal ? { reveal: 1 } : undefined })" in totp
    assert "IciciTotpPanel" in (ui / "components" / "PortfolioSummary.tsx").read_text()      # BRKR renders it
    assert "IciciTotpPanel" not in (ui / "components" / "gold" / "GoldPage.tsx").read_text()
    # the server side: the paths exist under the prefixes main.py mounts
    main = (api / "main.py").read_text()
    assert 'app.include_router(gold.router, prefix="/api/gold"' in main
    assert 'app.include_router(gold_preopen.router, prefix="/api/commodity"' in main, "PLAN §d: the aliases stay one release (side A needs them)"
    assert 'app.include_router(positions.router, prefix="/api/positions"' in main and 'app.include_router(mcx.router, prefix="/api/mcx"' in main
    assert '@router.get("/health")' in (api / "routers" / "gold.py").read_text() and '@router.get("/contracts")' in (api / "routers" / "gold.py").read_text()
    assert '@router.get("/totp/status")' in (api / "routers" / "positions.py").read_text()
    assert '@router.get("/specs")' in (api / "routers" / "mcx.py").read_text(), "side A (25 Oct UI) still calls /api/mcx/specs"
    gp = (api / "routers" / "gold_preopen.py").read_text()
    assert '@router.get("/gold-preopen")' in gp and '@router.get("/gold-preopen/log")' in gp
    # side A = the pre-gold 25 Oct release itself (NOT ui/dist/previous: once GOLD shipped, "previous" is a gold release and
    # the A-only premise no longer holds — that is what hung the suite on 5 Nov: a failing `in` over megabytes made pytest
    # diff the whole bundle). Skipped when build_ui.sh has pruned that release. Booleans only, so a failure never diffs a bundle.
    side_a = ROOT / "ui" / "dist" / "releases" / "20261025-223942-0ae66db"
    if side_a.exists():
        bundle = "".join(f.read_text(errors="replace") for f in side_a.rglob("*.js") if f.stat().st_size < 4_000_000)
        has_specs = 'i("/api/mcx/specs")' in bundle or '("/api/mcx/specs")' in bundle
        has_preopen = ('get("/api/commodity/gold-preopen",{params:' in bundle
                       and 'get("/api/commodity/gold-preopen/log",{params:{threshold:' in bundle)
        has_gold = "/api/gold/" in bundle or "/api/positions/totp" in bundle
        assert has_specs, "side A no longer calls /api/mcx/specs"
        assert has_preopen, "side A no longer calls the gold-preopen aliases"
        assert not has_gold, "side A already calls /api/gold: it is not the pre-gold release"


def test_expected_new_page_is_gold_only():
    gold = netpolicy.expected_new_page("gold")
    assert gold is not None and gold.code == "GOLD" and "no" in gold.note.lower()
    assert netpolicy.expected_new_page("brief") is None and netpolicy.expected_new_page("GOLD") is None
    assert [p.id for p in netpolicy.EXPECTED_NEW_PAGES] == ["gold"]


def test_partition_structure_sets_aside_only_declared_patterns_per_tab_field_and_side():
    declared, undeclared = netpolicy.partition_structure("commodity", "panels", "a",
                                                         ["Gold Pre-Open Desk", "Accuracy log", "Oil board"])
    assert declared == ["Gold Pre-Open Desk", "Accuracy log"] and undeclared == ["Oil board"]
    assert netpolicy.partition_structure("commodity", "panels", "b", ["Gold Pre-Open Desk"]) == ([], ["Gold Pre-Open Desk"])
    assert netpolicy.partition_structure("commodity", "table_headers", "a", ["Day | Settlement | Fair open #:#"]) == \
        (["Day | Settlement | Fair open #:#"], [])
    assert netpolicy.partition_structure("brief", "panels", "a", ["Gold open (MCX)", "Your book"]) == (["Gold open (MCX)"], ["Your book"])
    assert netpolicy.partition_structure("mcxgold", "panels", "b", ["Contracts — MCX gold family", "Quote"]) == \
        (["Contracts — MCX gold family"], ["Quote"])
    # pinned (wave 1b): a retained overlay panel or a second specs-like panel on B is drift, not the declared change
    assert netpolicy.partition_structure("mcxgold", "panels", "b", ["COMEX × rupee overlay", "Contract selector", "Contract specs — MCX gold family"]) == \
        ([], ["COMEX × rupee overlay", "Contract selector", "Contract specs — MCX gold family"])
    assert netpolicy.partition_structure("mcxgold", "panels", "a", ["COMEX × rupee overlay", "Contract specs — MCX gold family"]) == \
        (["COMEX × rupee overlay", "Contract specs — MCX gold family"], [])
    ladder = "Expiry | Source | settle ₹/# g | band ₹ | OI lots | ΔOI lots | carry % p.a. | COMEX month | Tender"
    assert netpolicy.partition_structure("mcxgold", "table_headers", "b", [ladder, "Contract | Lot | Quote | Tick"]) == \
        ([ladder], ["Contract | Lot | Quote | Tick"])
    assert netpolicy.normalize_text("Expiry | Source | settle ₹/10 g | band ₹") == "Expiry | Source | settle ₹/# g | band ₹"
    assert netpolicy.partition_structure("broker", "panels", "b", ["Auto-login (TOTP)", "TOTP secrets"]) == (["Auto-login (TOTP)"], ["TOTP secrets"])
    assert netpolicy.partition_structure("desk", "panels", "a", ["Book"]) == ([], ["Book"])      # no declaration
    assert netpolicy.partition_structure(None, "panels", "a", ["Book"]) == ([], ["Book"])
    assert netpolicy.partition_structure("world", "panels", "a", ["X"]) == ([], ["X"])            # note-only entry
    assert "tables" in netpolicy.structure_delta("commodity").counts and netpolicy.structure_delta("brief").counts == frozenset()


def test_compare_sets_declared_structure_deltas_aside_but_keeps_undeclared_ones():
    fp_a = dict(_visit()["fingerprint"], panels=["Book", "Gold Pre-Open Desk", "Accuracy log"], tables=3,
                table_headers=["A | B", "Day | Settlement | Fair open #:#"])
    fp_b = dict(_visit()["fingerprint"], panels=["Book"], tables=1, table_headers=["A | B"])
    r = parity.compare(_visit(fingerprint=fp_a, tab="commodity"), _events(), _visit(fingerprint=fp_b, tab="commodity"), _events())
    assert r["reasons"] == [], r["reasons"]
    # one-sided entries come out of _multiset_diff sorted
    assert r["diff"]["expected_structure"] == {"panels": {"a_only": ["Accuracy log", "Gold Pre-Open Desk"], "b_only": []},
                                               "table_headers": {"a_only": ["Day | Settlement | Fair open #:#"], "b_only": []},
                                               "tables": {"a": 3, "b": 1}}
    assert any("expected structure deltas set aside" in n for n in r["notes"])
    # an explicit tab= wins over the visits' tab; an undeclared difference on the same page is still a DIFF
    fp_a2 = dict(fp_a, panels=fp_a["panels"] + ["Oil board"])
    r2 = parity.compare(_visit(fingerprint=fp_a2), _events(), _visit(fingerprint=fp_b), _events(), tab="commodity")
    assert [x for x in r2["reasons"] if x.startswith("panels differ")] == ["panels differ: only A ['Oil board'], only B []"]
    assert r2["diff"]["panels_only_a"] == ["Oil board"] and "expected_structure" in r2["diff"]
    # without a tab nothing is declared; with --no-expected-deltas nothing is set aside either
    r3 = parity.compare(_visit(fingerprint=fp_a), _events(), _visit(fingerprint=fp_b), _events())
    assert any(x.startswith("panels differ") for x in r3["reasons"]) and any(x.startswith("tables:") for x in r3["reasons"])
    r4 = parity.compare(_visit(fingerprint=fp_a, tab="commodity"), _events(), _visit(fingerprint=fp_b, tab="commodity"),
                        _events(), expected=False)
    assert len(r4["reasons"]) == 3 and "expected_structure" not in r4["diff"]
    # a declared count delta on a page whose declaration has no counts stays a DIFF (same table headers on both sides:
    # brief declares no table_headers patterns, so a one-sided header would be a second, undeclared DIFF)
    r5 = parity.compare(_visit(fingerprint=dict(fp_a, panels=["Book", "Gold open (MCX)"], tables=2, table_headers=["A | B"]),
                               tab="brief"), _events(),
                        _visit(fingerprint=dict(fp_b, tables=1), tab="brief"), _events())
    assert r5["reasons"] == ["tables: A 2 vs B 1"] and r5["diff"]["expected_structure"]["panels"]["a_only"] == ["Gold open (MCX)"]


def test_new_page_result_and_engine_summary_treat_a_new_page_as_b_audit_only():
    vb = _visit(url="http://127.0.0.1:8010/?tab=gold", tab="gold")
    new_ok = parity.new_page_result("gold", "GOLD", vb, _events(), strict=False)
    assert new_ok["verdict"] == "NEW" and new_ok["a"] is None and new_ok["a_pass"] is None and new_ok["b_pass"] is True
    assert new_ok["reasons"] == [] and new_ok["notes"] and "no A side" in new_ok["notes"][0]
    new_bad = parity.new_page_result("gold", "GOLD", vb, _events(console_errors=["boom"]), strict=False)
    assert new_bad["b_pass"] is False

    def row(verdict, a_pass=True, b_pass=True, **diff):
        side_ok = parity._side(_visit(), _events(), False)
        side_bad = parity._side(_visit(), _events(page_errors=["TypeError: x"]), False)
        return {"code": "X", "verdict": verdict, "reasons": [] if verdict == "PARITY" else ["x"], "diff": diff, "notes": [],
                "attempts": 2 if verdict == "PARITY" else 1, "a": side_ok if a_pass else side_bad,
                "b": side_ok if b_pass else side_bad, "a_pass": a_pass, "b_pass": b_pass}

    results = {"brief": row("PARITY", expected_structure={"panels": {}}), "desk": row("DIFF", b_pass=False),
               "world": row("PARITY", expected_deltas={}), "gold": new_ok}
    s = parity.summarize_results(results)
    assert (s["tabs"], s["compared"], s["parity"], s["diff"], s["new"]) == (4, 3, 2, ["desk"], ["gold"])
    assert s["new_failed"] == [] and s["b_failed"] == ["desk"] and s["a_failed"] == []
    assert s["resolved_on_retry"] == ["brief", "world"] and s["expected_structure_tabs"] == ["brief"]
    assert s["expected_delta_tabs"] == ["world"] and s["b_failures_non_seam"] == ["desk"]
    assert parity.engine_ok(s) is False
    s2 = parity.summarize_results({"brief": row("PARITY"), "gold": new_ok})
    assert parity.engine_ok(s2) is True and (s2["parity"], s2["compared"], s2["new"]) == (1, 1, ["gold"])
    s3 = parity.summarize_results({"brief": row("PARITY"), "gold": new_bad})
    assert s3["new_failed"] == ["gold"] and parity.engine_ok(s3) is False, "a NEW page must still pass its B audit"
    md = parity.render_markdown({"meta": {"a": "A", "b": "B", "started_at": "t0", "wait_s": 3, "retries": 1},
                                 "engines": {"webkit": {"browser_version": "v", "summary": s, "tabs": results}}, "ok": False})
    assert "2/3 PARITY + 1 NEW (no A side: gold)" in md and "| gold | GOLD | NEW | — | yes | — |" in md
    assert "NEW pages failing their B audit: none" in md and "intended structure deltas (set aside): brief" in md


def test_ui_audit_repetition_rule_counts_fair_open_titles_only():
    fp = {"panels": ["Today's open · fair open 08:45", "Accuracy log"], "headings": ["Fair open model"], "table_headers": []}
    assert ui_audit.repetition_hits(fp) == ["Today's open · fair open 08:45", "Fair open model"]
    assert ui_audit.repetition_hits(None) == [] and ui_audit.repetition_hits({"panels": ["Book"]}) == []
    lines = ui_audit.tab_failures(_visit(fingerprint=dict(_visit()["fingerprint"], **fp)), _events(), strict=False)
    assert len(lines) == 1 and lines[0].startswith("repetition: 'fair open' named by 2 panels/headings")
    one = dict(_visit()["fingerprint"], panels=["Fair open (model)"], headings=[])
    assert ui_audit.tab_failures(_visit(fingerprint=one), _events(), strict=False) == []
    assert ui_audit.tab_failures(_visit(), _events(console_errors=["boom"]), strict=False) == ["console_error: boom"]


# ── scratch proxy in front of the real Host/Origin guard (FX-PY adversarial check) ──────────────────────────

def test_forward_headers_are_what_nexts_rewrite_sends():
    h = scratch_server.forward_headers([("host", "127.0.0.1:8093"), ("origin", "http://127.0.0.1:8093"),
                                        ("x-forwarded-host", "evil.example"), ("connection", "keep-alive"),
                                        ("content-type", "application/json")], "127.0.0.1:8093")
    assert h == {"origin": "http://127.0.0.1:8093", "content-type": "application/json", "x-forwarded-host": "127.0.0.1:8093"}
    assert "x-forwarded-host" not in scratch_server.forward_headers([("x-forwarded-host", "evil.example")], None)


@pytest.fixture()
def guarded_scratch(tmp_path):
    """scratch_server.create_app in front of a FastAPI backend wrapped in the REAL shared/http_guard.py."""
    from fastapi.testclient import TestClient

    sys.path.insert(0, str(ROOT))
    from shared.http_guard import install_http_guard

    backend = FastAPI()
    seen: list[dict] = []

    @backend.api_route("/api/echo", methods=["GET", "POST"])
    async def echo(request: Request) -> dict:
        seen.append({k: v for k, v in request.headers.items() if k in ("host", "origin", "x-forwarded-host")})
        return {"ok": True}

    install_http_guard(backend, service="test-backend", env={})
    (tmp_path / "index.html").write_text("x")
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=backend), base_url="http://127.0.0.1:8010")
    app = scratch_server.create_app(tmp_path, "http://127.0.0.1:8010", client=client)
    return TestClient(app, base_url="http://127.0.0.1:8093"), seen


def test_scratch_proxy_same_origin_write_reaches_the_guarded_backend(guarded_scratch):
    c, seen = guarded_scratch
    r = c.post("/api/echo", json={}, headers={"Origin": "http://127.0.0.1:8093"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert seen[-1] == {"host": "127.0.0.1:8010", "origin": "http://127.0.0.1:8093", "x-forwarded-host": "127.0.0.1:8093"}
    # a client-sent X-Forwarded-Host is replaced by the page's real Host, never relayed
    r = c.post("/api/echo", json={}, headers={"Origin": "http://127.0.0.1:8093", "X-Forwarded-Host": "evil.example"})
    assert r.status_code == 200 and seen[-1]["x-forwarded-host"] == "127.0.0.1:8093"


def test_scratch_proxy_does_not_launder_a_cross_site_write(guarded_scratch):
    c, seen = guarded_scratch
    n = len(seen)
    r = c.post("/api/echo", content=b"{}", headers={"Origin": "https://evil.example", "Content-Type": "text/plain"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "unauthorized" and len(seen) == n
    assert c.post("/api/echo", json={}, headers={"Origin": "http://127.0.0.1:8093", "Sec-Fetch-Site": "cross-site"}
                  ).status_code == 403


def test_without_x_forwarded_host_the_guard_refuses_the_same_write(guarded_scratch, monkeypatch):
    """Negative control: the pre-fix proxy (Origin forwarded, no X-Forwarded-Host) gets 403 for a same-origin POST."""
    c, seen = guarded_scratch
    monkeypatch.setattr(scratch_server, "forward_headers",
                        lambda items, _host: {k: v for k, v in items if k.lower() not in scratch_server.HOP_BY_HOP})
    n = len(seen)
    r = c.post("/api/echo", json={}, headers={"Origin": "http://127.0.0.1:8093"})
    assert r.status_code == 403 and len(seen) == n


# ── a stopped scratch server lets go of the backend (25 Oct: lingering relays held sockets on the live ui-api) ─

def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_scratch_server_exits_promptly_on_sigterm_with_a_relayed_stream_open(tmp_path):
    """A relayed SSE stream never ends by itself; SIGTERM must still stop the server within seconds and close
    its upstream socket (uvicorn's graceful shutdown is bounded and the lifespan closes the upstream client)."""
    import http.client
    import signal
    import subprocess
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    upstream_closed = threading.Event()

    class Backend(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # an endless SSE stream
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            try:
                while True:
                    self.wfile.write(b"9\r\ndata: x\n\n\r\n")
                    self.wfile.flush()
                    time.sleep(0.2)
            except OSError:
                upstream_closed.set()

        def log_message(self, *_a: object) -> None:
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    (tmp_path / "index.html").write_text("x")
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "desktop_qa" / "scratch_server.py"), "--ui", str(tmp_path),
                             "--port", str(port), "--allow-any-port", "--backend", f"http://127.0.0.1:{backend.server_address[1]}"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    conn = None
    try:
        for _ in range(100):
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/api/sse")
                resp = conn.getresponse()
                break
            except OSError:
                conn = None
                time.sleep(0.1)
        assert conn is not None, "scratch server did not start"
        assert resp.status == 200 and b"data: x" in resp.read1(64)
        t0 = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pytest.fail("SIGTERM did not stop the scratch server within 10 s (a relayed stream kept it alive)")
        assert time.monotonic() - t0 < 10
        assert upstream_closed.wait(5), "the upstream (backend) stream was left open"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if conn is not None:
            conn.close()
        backend.shutdown()
        backend.server_close()


def test_scratch_server_exits_promptly_on_sigterm_with_a_relayed_websocket_open(tmp_path):
    """The same for a relayed WebSocket (the monitor socket): SIGTERM stops the server within seconds and the
    backend sees its WebSocket closed, so a stopped QA server never keeps a socket open on the live ui-api."""
    import http.client
    import signal
    import subprocess
    import threading
    import time

    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect as ws_connect
    from websockets.sync.server import serve as ws_serve

    upstream_closed = threading.Event()

    def handler(conn) -> None:  # an endless monitor feed
        try:
            while True:
                conn.send("tick")
                time.sleep(0.2)
        except ConnectionClosed:
            upstream_closed.set()

    backend = ws_serve(handler, "127.0.0.1", 0)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    backend_port = backend.socket.getsockname()[1]
    (tmp_path / "index.html").write_text("x")
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "desktop_qa" / "scratch_server.py"), "--ui", str(tmp_path),
                             "--port", str(port), "--allow-any-port", "--backend", f"http://127.0.0.1:{backend_port}"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = None
    try:
        for _ in range(100):
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                c.request("GET", "/__qa/health")
                if c.getresponse().status == 200:
                    break
            except OSError:
                time.sleep(0.1)
        client = ws_connect(f"ws://127.0.0.1:{port}/api/monitor/ws/monitor", open_timeout=5)
        assert client.recv(timeout=5) == "tick", "the relay forwards the backend's messages"
        t0 = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pytest.fail("SIGTERM did not stop the scratch server within 10 s (a relayed WebSocket kept it alive)")
        assert time.monotonic() - t0 < 10
        assert upstream_closed.wait(5), "the upstream (backend) WebSocket was left open"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if client is not None:
            client.close()
        backend.shutdown()
