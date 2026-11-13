"""Static contract tests for the desktop program (reports/desktop_app/PLAN.md §5, AC-11, AC-1/2 wiring).

These read files only (no build, no browser, no live stack) and run in the core suite (and in CI). The program
is delivered, so a test FAILS when a file it checks is missing or no longer has the shape it parses, as well as
when the file breaks the frozen contract: drift must never pass as a skip (desktop review completeness-05). A
partial checkout without the desktop sources (e.g. only the Python services) opts out explicitly with
``DESKTOP_CONTRACT_ALLOW_SKIP=1``, which turns exactly those cases back into skips. The tests check:

* the Rust Go-menu page table (desktop/src-tauri/src/pages.rs) equals ui/app/page.tsx COMMAND_PAGES (ids,
  codes, labels, order), covers every TAB_ID, and its ⌘1–⌘9 map equals the UI's ALT+1…9 page strip; the page
  count is 43 since the gold program (reports/gold_program/PLAN.md Appendix A: the GOLD page; the GOLD-specific
  checks live in tests/integration/test_gold_gates.py)
* the capability for the remote origin http://127.0.0.1:8010 resolves to exactly the nine shell_* commands,
  with no plugin permissions (in particular no fs / shell / process / http), and no boot command
* build.rs declares an AppManifest with exactly the 14 contract commands, and generate_handler! registers
  the same set; tauri.conf.json has identifier/productName and a CSP
* the UI platform bridge (ui/lib/platform) references exactly the nine contract command names, the shell
  marker and the shell event, and no boot command
* scripts/build_ui.sh is executable; services/ui-api/static_ui.py exports mount_static_ui; main.py (once
  patched) calls it exactly once, after every router/route registration
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from desktop_qa import tauri_acl
from desktop_qa.pages import PAGE_TSX, load_page_source, parse_rust_pages

SRC_TAURI = ROOT / "desktop" / "src-tauri"
PAGES_RS = SRC_TAURI / "src" / "pages.rs"
PLATFORM_DIR = ROOT / "ui" / "lib" / "platform"
BUILD_UI = ROOT / "scripts" / "build_ui.sh"
STATIC_UI = ROOT / "services" / "ui-api" / "static_ui.py"
UI_API_MAIN = ROOT / "services" / "ui-api" / "main.py"

REMOTE_ORIGIN = ("http", "127.0.0.1", 8010)
REMOTE_COMMANDS = frozenset({
    "shell_info", "shell_status", "shell_notify", "shell_notification_permission",
    "shell_request_notification_permission", "shell_save_download", "shell_open_external", "shell_new_window",
    "shell_set_title",
})
BOOT_COMMANDS = frozenset({"boot_status", "stack_start", "stack_stop", "open_logs", "open_terminal"})
FORBIDDEN_PLUGINS = ("fs", "shell", "process", "http")
# PM-approved amendments to the remote grant ONLY (resolved command keys, e.g. "plugin:window|start_dragging").
# Empty = the frozen contract v1: the remote origin gets the nine shell_* commands and nothing else.
REMOTE_EXTRA_ALLOWED: frozenset[str] = frozenset({
    # PM-approved amendment (D2 patch 2): overlay title-strip dragging + double-click zoom on the calling window only
    "plugin:window|start_dragging",
    "plugin:window|internal_toggle_maximize",
})


ALLOW_SKIP_ENV = "DESKTOP_CONTRACT_ALLOW_SKIP"


def missing(reason: str) -> NoReturn:
    """A source the contract needs is absent or reshaped: fail (skip only with the explicit partial-checkout opt-out)."""
    if os.environ.get(ALLOW_SKIP_ENV) == "1":
        pytest.skip(f"{reason} ({ALLOW_SKIP_ENV}=1: partial checkout)")
    pytest.fail(f"{reason}. The desktop program is delivered, so this is drift; in a partial checkout without the "
                f"desktop sources set {ALLOW_SKIP_ENV}=1", pytrace=False)


def need(path: Path, owner: str) -> None:
    if not path.exists():
        missing(f"{path.relative_to(ROOT)} is missing ({owner})")


@pytest.fixture(scope="module")
def ui_pages():
    return load_page_source(PAGE_TSX)


# ── Go-menu page table ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rust_pages():
    need(PAGES_RS, "D2 shell")
    return parse_rust_pages(PAGES_RS.read_text())


PAGE_COUNT = 44   # 43 + the FINAL round's GPLN page (wave E); pages.rs PAGE_COUNT must agree


def test_page_source_is_self_consistent(ui_pages):
    assert len(ui_pages.tab_ids) == PAGE_COUNT, (f"page.tsx TAB_IDS lists {len(ui_pages.tab_ids)} pages, expected "
                                                 f"{PAGE_COUNT} (gold program: B4A registers the GOLD page)")
    assert {p.id for p in ui_pages.command_pages} == set(ui_pages.tab_ids)


def test_rust_page_table_equals_command_pages(ui_pages, rust_pages):
    ui = [(p.id, p.code, p.label) for p in ui_pages.command_pages]
    rs = [(p.id, p.code, p.label) for p in rust_pages]
    only_ui, only_rs = sorted(set(ui) - set(rs)), sorted(set(rs) - set(ui))
    assert not only_ui and not only_rs, f"pages.rs drift — missing in Rust: {only_ui}; not in page.tsx: {only_rs}"
    assert rs == ui, "pages.rs has the same pages as COMMAND_PAGES but in a different order"


def test_rust_page_table_covers_all_tab_ids(ui_pages, rust_pages):
    ids = [p.id for p in rust_pages]
    assert len(ids) == len(set(ids)) == PAGE_COUNT
    assert set(ids) == set(ui_pages.tab_ids)
    src = PAGES_RS.read_text()
    assert f"pub const PAGE_COUNT: usize = {PAGE_COUNT};" in src, "pages.rs PAGE_COUNT drifted from the test's PAGE_COUNT"


def test_rust_shortcuts_match_alt_digit_pages(ui_pages):
    need(PAGES_RS, "D2 shell")
    src = PAGES_RS.read_text()
    fields = re.findall(r'id:\s*"([^"]+)"[^}]*?shortcut:\s*(\d+)', src)
    if not fields:
        missing("pages.rs has no per-page `shortcut` field (moved elsewhere? update this test with it)")
    by_digit: dict[int, list[str]] = {}
    for tab, digit in fields:
        if int(digit):
            by_digit.setdefault(int(digit), []).append(tab)
    assert all(len(v) == 1 for v in by_digit.values()), f"a digit is bound twice: {by_digit}"
    expected = {i + 1: tab for i, tab in enumerate(ui_pages.tab_strip[:9])}   # ALT+1..9 = tabList[0..8]
    assert {d: v[0] for d, v in by_digit.items()} == expected


def test_ui_desktop_page_meta_equals_command_pages(ui_pages):
    """D4's title-strip copy (ui/components/desktop/pages.ts PAGE_META) must not drift from COMMAND_PAGES."""
    meta_ts = ROOT / "ui" / "components" / "desktop" / "pages.ts"
    need(meta_ts, "D4 desktop UX")
    rows = re.findall(r"(?m)^\s*['\"]?([a-z]+)['\"]?\s*:\s*\{\s*code:\s*'((?:[^'\\]|\\.)*)'\s*,\s*label:\s*'((?:[^'\\]|\\.)*)'",
                      meta_ts.read_text())
    if not rows:
        missing("ui/components/desktop/pages.ts PAGE_META entries are not in the `id: { code: '..', label: '..' }` shape")
    got = {i: (c, re.sub(r"\\(.)", r"\1", lab)) for i, c, lab in rows}
    want = {p.id: (p.code, p.label) for p in ui_pages.command_pages}
    assert got == want, (f"PAGE_META drift — missing {sorted(want.keys() - got.keys())}, unknown "
                         f"{sorted(got.keys() - want.keys())}, changed {sorted(k for k in want.keys() & got.keys() if want[k] != got[k])}")


# ── capabilities (least privilege) ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def acl():
    need(SRC_TAURI, "D2 shell")
    return tauri_acl.Acl.load(SRC_TAURI)


@pytest.fixture(scope="module")
def capabilities():
    need(SRC_TAURI / "capabilities", "D2 shell")
    caps = tauri_acl.load_capabilities(SRC_TAURI)
    if not caps:
        missing("desktop/src-tauri/capabilities has no capability files (D2 shell)")
    return caps


NO_REMOTE = ("no capability grants the remote origin http://127.0.0.1:8010 — terminal windows could not call "
             "the nine shell_* commands (PLAN §5)")


@pytest.fixture(scope="module")
def remote_caps(capabilities):
    return [c for c in capabilities if tauri_acl.is_remote(c)]


def _resolved(acl, caps) -> set[str]:
    out: set[str] = set()
    for cap in caps:
        for entry in cap.get("permissions", []):
            out |= acl.resolve(tauri_acl.permission_id(entry))
    return out


def test_every_capability_permission_resolves(acl, capabilities):
    bad = []
    for cap in capabilities:
        for entry in cap.get("permissions", []):
            try:
                acl.resolve(tauri_acl.permission_id(entry))
            except tauri_acl.AclError as exc:
                bad.append(f"{cap['_file']}: {exc}")
    assert not bad, "unresolvable permissions (typo, or gen/schemas stale — run a cargo build):\n" + "\n".join(bad)


def test_remote_capability_origin_is_exactly_ui_api(remote_caps):
    assert remote_caps, NO_REMOTE
    for cap in remote_caps:
        for url in cap["remote"]["urls"]:
            p = urlsplit(url)
            assert (p.scheme, p.hostname, p.port) == REMOTE_ORIGIN, (
                f"{cap['_file']}: remote URL {url!r} is not exactly http://127.0.0.1:8010 (no wildcards, no "
                f"localhost alias, no other port)")
            assert "*" not in p.netloc, f"{cap['_file']}: wildcard in remote host/port {url!r}"


def test_remote_capability_grants_exactly_the_nine_shell_commands(acl, remote_caps):
    assert remote_caps, NO_REMOTE
    granted = _resolved(acl, remote_caps)
    extra = granted - REMOTE_COMMANDS - REMOTE_EXTRA_ALLOWED
    missing = REMOTE_COMMANDS - granted
    assert not extra, f"remote origin is granted more than the contract: {sorted(extra)}"
    assert not missing, f"remote origin lacks contract commands: {sorted(missing)}"


def test_remote_capability_has_no_fs_shell_process_http(remote_caps):
    assert remote_caps, NO_REMOTE
    ids = [tauri_acl.permission_id(e) for c in remote_caps for e in c.get("permissions", [])]
    forbidden = [i for i in ids if tauri_acl.split_identifier(i)[0].split(":")[0] in FORBIDDEN_PLUGINS]
    assert not forbidden, f"fs/shell/process/http permissions granted to the remote origin: {forbidden}"


def test_remote_capability_has_only_app_command_permissions(acl, remote_caps):
    """Contract v1: the remote grant is app commands only. A plugin/core permission is accepted only when every
    command it resolves to is in REMOTE_EXTRA_ALLOWED (a PM-approved amendment)."""
    assert remote_caps, NO_REMOTE
    ids = [tauri_acl.permission_id(e) for c in remote_caps for e in c.get("permissions", [])]
    unapproved = {i: sorted(acl.resolve(i)) for i in ids if ":" in i and not acl.resolve(i) <= REMOTE_EXTRA_ALLOWED}
    assert not unapproved, (f"plugin/core permissions granted to the remote origin without a PM-approved contract "
                            f"amendment (REMOTE_EXTRA_ALLOWED): {unapproved}")


def test_boot_commands_never_reach_the_remote_origin(acl, remote_caps):
    assert remote_caps, NO_REMOTE
    leaked = _resolved(acl, remote_caps) & BOOT_COMMANDS
    assert not leaked, f"boot-only commands granted to the remote origin: {sorted(leaked)}"


def test_boot_commands_are_granted_to_local_content_only(acl, capabilities):
    for cap in capabilities:
        if _resolved(acl, [cap]) & BOOT_COMMANDS:
            assert not tauri_acl.is_remote(cap), f"{cap['_file']} grants boot commands AND has remote URLs"
    local = _resolved(acl, [c for c in capabilities if not tauri_acl.is_remote(c)])
    assert BOOT_COMMANDS <= local, f"boot page cannot call {sorted(BOOT_COMMANDS - local)} (no local grant)"


def test_app_manifest_declares_exactly_the_contract_commands():
    need(SRC_TAURI / "build.rs", "D2 shell")
    cmds = tauri_acl.app_manifest_commands(SRC_TAURI)
    assert cmds is not None, ("build.rs declares no AppManifest::commands — without it every registered command "
                              "is callable by local content and none can be granted per origin")
    assert len(cmds) == len(set(cmds))
    assert set(cmds) == REMOTE_COMMANDS | BOOT_COMMANDS, (
        f"AppManifest drift — extra {sorted(set(cmds) - REMOTE_COMMANDS - BOOT_COMMANDS)}, "
        f"missing {sorted(REMOTE_COMMANDS | BOOT_COMMANDS - set(cmds))}")


def test_registered_handlers_equal_the_app_manifest():
    need(SRC_TAURI / "src", "D2 shell")
    handlers = tauri_acl.registered_handlers(SRC_TAURI)
    cmds = tauri_acl.app_manifest_commands(SRC_TAURI)
    if handlers is None or cmds is None:
        missing("desktop/src-tauri has no generate_handler! or no AppManifest (D2 shell)")
    assert set(handlers) == set(cmds), (f"registered but not in the manifest: {sorted(set(handlers) - set(cmds))}; "
                                        f"in the manifest but not registered: {sorted(set(cmds) - set(handlers))}")


def test_tauri_conf_identity_and_csp():
    conf_path = SRC_TAURI / "tauri.conf.json"
    need(conf_path, "D2 shell")
    conf = json.loads(conf_path.read_text())
    assert conf.get("identifier") == "ai.suryadhana.terminal"
    assert conf.get("productName") == "SuryaDhana"
    csp = ((conf.get("app") or {}).get("security") or {}).get("csp")
    assert csp, "app.security.csp is not set (AC-11: strict CSP on the boot page)"
    text = csp if isinstance(csp, str) else json.dumps(csp)
    assert "default-src" in text, f"CSP has no default-src: {text[:200]}"


def test_status_heartbeat_is_inside_the_ui_contract():
    """C1-desktop-native-03: the shell's status heartbeat (health.rs STATUS_HEARTBEAT, plus its 1 s ticker) must
    stay within the interval the UI relies on (ui/components/desktop/status.ts SHELL_STATUS_MAX_INTERVAL_MS)."""
    health = SRC_TAURI / "src" / "health.rs"
    status = ROOT / "ui" / "components" / "desktop" / "status.ts"
    need(health, "D2 shell")
    need(status, "D4 desktop UX")
    m = re.search(r"pub const STATUS_HEARTBEAT: Duration = Duration::from_secs\((\d+)\);", health.read_text())
    assert m, "health.rs has no STATUS_HEARTBEAT constant"
    heartbeat_ms = int(m.group(1)) * 1000 + 1000  # + the 1 s ticker that checks it
    m = re.search(r"export const SHELL_STATUS_MAX_INTERVAL_MS = ([\d_]+)", status.read_text())
    assert m, "status.ts has no SHELL_STATUS_MAX_INTERVAL_MS"
    contract_ms = int(m.group(1).replace("_", ""))
    assert heartbeat_ms <= contract_ms, f"shell heartbeat {heartbeat_ms} ms exceeds the UI contract {contract_ms} ms"


# ── UI platform bridge (D3) ────────────────────────────────────────────────────────────────────────

def _strip_ts_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"(?m)(^|[^:'\"`])//[^\n]*", r"\1", src)


@pytest.fixture(scope="module")
def bridge_source() -> str:
    need(PLATFORM_DIR, "D3 bridge")
    files = sorted(p for p in PLATFORM_DIR.rglob("*") if p.suffix in (".ts", ".tsx") and ".test." not in p.name)
    if not files:
        missing("ui/lib/platform has no TypeScript (D3 bridge)")
    return "\n".join(_strip_ts_comments(p.read_text()) for p in files)


def test_bridge_references_exactly_the_contract_commands(bridge_source):
    names = set(re.findall(r"\b(shell_[a-z_]+)\b", bridge_source))
    assert names == REMOTE_COMMANDS, (f"bridge command names drift — unknown {sorted(names - REMOTE_COMMANDS)}, "
                                      f"missing {sorted(REMOTE_COMMANDS - names)}")


def test_bridge_never_references_boot_commands(bridge_source):
    found = sorted({n for n in BOOT_COMMANDS if re.search(rf"\b{n}\b", bridge_source)})
    assert not found, f"the remote UI must not know boot-only commands: {found}"


def test_bridge_uses_contract_marker_and_event(bridge_source):
    assert "__SURYADHANA_SHELL__" in bridge_source, "detection marker window.__SURYADHANA_SHELL__ not referenced"
    assert "__TAURI_INTERNALS__" in bridge_source, "isDesktop() must also require window.__TAURI_INTERNALS__"
    assert "suryadhana:shell" in bridge_source, "shell event 'suryadhana:shell' not referenced"


# ── D1 web-serve wiring ────────────────────────────────────────────────────────────────────────────

def test_build_ui_script_is_executable():
    need(BUILD_UI, "D1 web-serve")
    assert os.access(BUILD_UI, os.X_OK), "scripts/build_ui.sh is not executable"
    assert BUILD_UI.read_text().startswith("#!"), "scripts/build_ui.sh has no shebang"


def test_static_ui_module_exports_mount():
    need(STATIC_UI, "D1 web-serve")
    tree = ast.parse(STATIC_UI.read_text())
    names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "mount_static_ui" in names


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute):
            return f.attr
    return None


def test_main_mounts_static_ui_once_and_last():
    need(UI_API_MAIN, "ui-api")
    src = UI_API_MAIN.read_text()
    if "mount_static_ui" not in src:
        missing("services/ui-api/main.py does not call mount_static_ui (D1 patch block)")
    tree = ast.parse(src)
    mounts = [n.lineno for n in ast.walk(tree) if _call_name(n) == "mount_static_ui"]
    assert len(mounts) == 1, f"mount_static_ui called {len(mounts)} times (lines {mounts})"
    registrations = []
    for n in ast.walk(tree):
        if _call_name(n) in ("include_router", "add_api_route", "add_api_websocket_route", "mount", "add_route"):
            registrations.append(n.lineno)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                f = d.func if isinstance(d, ast.Call) else d
                if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "app" \
                        and f.attr in ("get", "post", "put", "patch", "delete", "api_route", "websocket", "route"):
                    registrations.append(n.lineno)
    late = sorted(r for r in registrations if r > mounts[0])
    assert not late, f"routes registered after mount_static_ui (line {mounts[0]}): lines {late}"


# ── the skip policy itself ─────────────────────────────────────────────────────────────────────────

def test_missing_sources_fail_unless_a_partial_checkout_opts_out(monkeypatch, tmp_path):
    """completeness-05: a missing or reshaped source is a failure in a full checkout, a skip only on request."""
    monkeypatch.delenv(ALLOW_SKIP_ENV, raising=False)
    gone = ROOT / "desktop" / "src-tauri" / "src" / "no-such-file.rs"
    with pytest.raises(pytest.fail.Exception, match="drift"):
        need(gone, "D2 shell")
    with pytest.raises(pytest.fail.Exception, match="shape"):
        missing("pages.ts PAGE_META entries are not in the expected shape")
    monkeypatch.setenv(ALLOW_SKIP_ENV, "1")
    with pytest.raises(pytest.skip.Exception, match="partial checkout"):
        need(gone, "D2 shell")
    monkeypatch.setenv(ALLOW_SKIP_ENV, "0")   # only exactly "1" opts out
    with pytest.raises(pytest.fail.Exception):
        need(gone, "D2 shell")
