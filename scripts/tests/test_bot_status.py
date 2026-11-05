"""Telegram /status (scripts/master_controller._bot_status), desktop review round 3 (C-SECREL, F3-OPS).

* ui-api whose /health times out is shown HUNG (the 25 Oct wedge showed as a plain red dot), one that refuses the
  connection as down, and nothing else is asked of a ui-api that is not answering (each call would time out again);
* the terminal UI release line from GET /ready (SECREL-12): the build id, or MISSING with the build-ui remedy;
* the desktop app line: the installed bundle's own executable (never a self-test copy), and whether launchd
  supervises it (SECREL-06);
* the off-Mac dead-man ping (SECREL-02) and the unattended-reboot warning (completeness-final-04).

No live service is contacted: httpx gets a MockTransport, and ps / launchctl / pmset / defaults are stood in.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import master_controller as mc

BUILD = "20261025-153533-0ae66db"


class _NoJobs:
    def get_jobs(self) -> list:
        return []


def _run_status(monkeypatch, handler) -> tuple[str, list[str]]:
    """_bot_status with every HTTP call answered by ``handler(request)``; returns (reply, requested paths)."""
    seen: list[str] = []
    real = httpx.AsyncClient

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.url.host}:{request.url.port}{request.url.path}")
        return handler(request)

    monkeypatch.setattr(mc.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(wrapped),
                                                                        timeout=k.get("timeout")))
    monkeypatch.setattr(mc, "DATA_SVC", "http://127.0.0.1:8001")
    monkeypatch.setattr(mc, "UI_API", "http://127.0.0.1:8010")
    monkeypatch.setattr(mc, "scheduler", _NoJobs())
    monkeypatch.setattr(mc.tgbot, "otp_pending", lambda: False)
    monkeypatch.setattr(mc, "_mac_lines", lambda: ["(mac lines)"])
    return asyncio.run(mc._bot_status([])), seen


def _healthy(request: httpx.Request, *, ready: dict | None = None) -> httpx.Response:
    path = request.url.path
    if path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    if path == "/ready":
        return httpx.Response(200, json=ready or {"status": "ready", "ui": "ok", "ui_build_id": BUILD})
    if path == "/api/positions/open-positions":
        return httpx.Response(200, json={"connected": True})
    if path == "/api/config/setup-status":
        return httpx.Response(200, json={"checks": []})
    if path == "/db/nse-positions-meta":
        return httpx.Response(200, json={"tables": {"nse_bhavcopy": {"last": "2026-10-23"}}})
    return httpx.Response(404)


def test_healthy_stack_shows_the_served_terminal_ui_release(monkeypatch):
    reply, _ = _run_status(monkeypatch, _healthy)
    lines = reply.splitlines()
    assert lines[1:4] == ["🟢 data-service", "🟢 ui-api", f"🟢 terminal UI {BUILD}"]
    assert "(mac lines)" in lines and "🟢 ICICI session connected" in lines and "Setup to do: nothing" in lines


def test_a_missing_ui_release_is_red_with_its_remedy(monkeypatch):
    """SECREL-12: ui-api green, but the terminal shows 'UI build not found'."""
    reply, _ = _run_status(monkeypatch, lambda r: _healthy(r, ready={"status": "ready", "ui": "missing",
                                                                       "ui_build_id": None}))
    assert "🔴 terminal UI MISSING" in reply and "./start-local.sh build-ui" in reply and "--rollback" in reply


def test_a_ui_api_whose_health_times_out_is_shown_hung_and_asked_nothing_else(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == 8010:
            raise httpx.ReadTimeout("timed out", request=request)
        return _healthy(request)

    reply, seen = _run_status(monkeypatch, handler)
    assert "🔴 ui-api HUNG: listening, but /health gave no answer in 8 s" in reply
    assert "./start-local.sh restart ui-api" in reply and "🟢 data-service" in reply
    assert "about 3.5–5.5 min after it hung" in reply      # the watchdog's real timing, as RUNBOOK and status say
    assert "⚪ terminal UI and ICICI: unknown (ui-api is not answering)" in reply
    assert [p for p in seen if p.startswith("127.0.0.1:8010")] == ["127.0.0.1:8010/health"], seen
    assert "Data through: bhavcopy 2026-10-23" in reply


def test_a_refused_connection_is_down_not_hung(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port == 8001:
            raise httpx.ConnectError("refused", request=request)
        return _healthy(request)

    reply, seen = _run_status(monkeypatch, handler)
    assert "🔴 data-service down (not running): <code>./start-local.sh start data-service</code>" in reply
    assert "HUNG" not in reply and "Data through" not in reply
    assert [p for p in seen if p.startswith("127.0.0.1:8001")] == ["127.0.0.1:8001/health"]


def test_an_http_error_status_is_named(monkeypatch):
    reply, _ = _run_status(monkeypatch, lambda r: httpx.Response(503) if r.url.path == "/health" and r.url.port == 8010
                           else _healthy(r))
    assert "🔴 ui-api: /health answered HTTP 503" in reply


# ── the desktop app line ─────────────────────────────────────────────────────────────────────────────────────

def _bundle(tmp: Path) -> Path:
    app = tmp / "Applications" / "SuryaDhana.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_bytes(
        b'<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
        b"<key>CFBundleShortVersionString</key><string>1.0.0</string></dict></plist>")
    return app


def _commands(ps: str, job_pid: str | None, guard_pid: str = ""):
    def run(cmd: list[str]) -> str:
        if cmd[0] == "ps":
            return ps
        if cmd[0] == "launchctl":
            return f"gui/501/SuryaDhana = {{\n\tstate = running\n\tpid = {job_pid}\n}}\n" if job_pid else ""
        if cmd[0] == "pgrep":           # a crash guard (supervise.rs) watching guard_pid only
            return "77001\n" if guard_pid and cmd[1:] == ["-f", "--", f"suryadhana-crash-guard {guard_pid} "] else ""
        return ""
    return run


@pytest.mark.parametrize("job,login,guard,want", [
    ("83455", True, "", "🟢 desktop app 1.0.0 running (supervised by launchd)"),
    ("99999", True, "83455", "🟢 desktop app 1.0.0 running (opened by hand: its crash guard relaunches it)"),
    ("99999", True, "58496", "🟢 desktop app 1.0.0 running (opened by hand: not relaunched after a crash)"),
    ("99999", True, "", "🟢 desktop app 1.0.0 running (opened by hand: not relaunched after a crash)"),
    ("83455", False, "", "🟢 desktop app 1.0.0 running (Launch at Login off: not relaunched after a crash)"),
])
def test_desktop_app_line(monkeypatch, tmp_path, job, login, guard, want):
    app = _bundle(tmp_path)
    exe = app / "Contents" / "MacOS" / "SuryaDhana"
    plist = tmp_path / "SuryaDhana.plist"
    if login:
        plist.write_text("<plist/>")
    ps = (f"  58496 /repo/desktop/src-tauri/target/release/bundle/macos/SuryaDhana.app/Contents/MacOS/SuryaDhana --self-test\n"
          f"  83455 {exe} --autostart\n  90001 grep {exe}\n")
    monkeypatch.setattr(mc, "_APP_BUNDLES", (app,))
    monkeypatch.setattr(mc, "_APP_LOGIN_PLIST", plist)
    monkeypatch.setattr(mc, "_run_quiet", _commands(ps, job, guard))
    assert mc._desktop_app_line() == want


def test_desktop_app_line_ignores_a_self_test_copy_and_a_missing_install(monkeypatch, tmp_path):
    """SECREL-11's twin: a self-test copy under desktop/ is not the installed app."""
    app = _bundle(tmp_path)
    ps = "  58496 /repo/desktop/src-tauri/target/release/bundle/macos/SuryaDhana.app/Contents/MacOS/SuryaDhana --self-test\n"
    monkeypatch.setattr(mc, "_APP_BUNDLES", (app,))
    monkeypatch.setattr(mc, "_run_quiet", _commands(ps, "58496"))
    assert mc._desktop_app_line() == "⚪ desktop app 1.0.0: not running (optional)"
    monkeypatch.setattr(mc, "_APP_BUNDLES", (tmp_path / "nope.app",))
    assert mc._desktop_app_line().startswith("⚪ desktop app: not installed")


# ── dead-man ping and unattended reboots ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,state,want", [
    ("", None, "⚠️ No off-Mac alert: HEALTHCHECK_PING_URL is not set"),
    ("https://hc-ping.com/secret-uuid", None, "⚪ dead-man ping: configured, no ping recorded yet"),
    ("https://hc-ping.com/secret-uuid", (30, "ok"), "🟢 dead-man ping ok"),
    ("https://hc-ping.com/secret-uuid", (30, "fail"), "🟠 dead-man ping: reported the stack unhealthy"),
    ("https://hc-ping.com/secret-uuid", (30, "error"), "🔴 dead-man ping failing"),
    ("https://hc-ping.com/secret-uuid", (1800, "ok"), "⚠️ dead-man ping: the last one was 30 min ago"),
])
def test_deadman_line(monkeypatch, tmp_path, url, state, want):
    f = tmp_path / "deadman"
    if state:
        f.write_text(f"{int(time.time()) - state[0]} {state[1]}\n")
    monkeypatch.setattr(mc, "_DEADMAN_STATE", f)
    monkeypatch.setattr(mc, "_env_file_value", lambda k: url if k == "HEALTHCHECK_PING_URL" else "")
    line = mc._deadman_line()
    assert line.startswith(want) and "secret-uuid" not in line


@pytest.mark.parametrize("pmset,auto,want", [
    (" autorestartatconnect 0\n autorestart          0\n", "1\n",
     "⚠️ Unattended reboots: the Mac stays off after a power failure; macOS installs updates (and restarts) by itself"),
    (" autorestart          1\n", "0\n", None),
    ("", "", None),                                    # not a Mac / commands missing: no claim either way
])
def test_reboot_recovery_line(monkeypatch, pmset, auto, want):
    monkeypatch.setattr(mc, "_run_quiet", lambda cmd: pmset if cmd[0] == "pmset" else auto if cmd[0] == "defaults" else "")
    line = mc._reboot_recovery_line()
    if want is None:
        assert line is None
    else:
        assert line == want + " (RUNBOOK 'Unattended reboots')"


def test_run_quiet_never_raises():
    assert mc._run_quiet(["/nonexistent/binary-for-test"]) == ""
