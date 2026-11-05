"""scripts/daily_session_refresh.py: the token hand-off (P3), the token check (P4) and .env writes (P13).

Everything is faked: no ui-api, data-service, Breeze, Keychain, Telegram or real .env. Each test points ENV_FILE,
CACHE_FILE, BLOCK_FILE and SHOT_FILE at tmp_path.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import daily_session_refresh as dsr

ENV_TEXT = ("# SuryaDhana\nICICI_API_KEY=k\nICICI_API_SECRET=s\nICICI_SESSION_TOKEN=old-token\nICICI_PASSWORD=old\n"
            "EXECUTION_LIVE_ALLOWED=0\nTELEGRAM_BOT_TOKEN=123:abc\n")


class NetworkUsed(BaseException):
    """Raised by the guards below; a BaseException so no `except Exception` in the code under test can hide it."""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach ui-api, data-service or ICICI: the default httpx.post and the real Breeze check raise."""
    def refuse(*a: Any, **k: Any) -> Any:
        raise NetworkUsed("a test tried to use the network")
    monkeypatch.setattr(dsr.httpx, "post", refuse)
    monkeypatch.setattr(dsr._icici_admin(), "probe_breeze_connection", refuse)


@pytest.fixture
def files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    env = tmp_path / ".env"
    env.write_text(ENV_TEXT)
    os.chmod(env, 0o600)
    monkeypatch.setattr(dsr, "ENV_FILE", env)
    monkeypatch.setattr(dsr, "CACHE_FILE", tmp_path / ".session_cache.json")
    monkeypatch.setattr(dsr, "BLOCK_FILE", tmp_path / ".icici_login_block.json")
    monkeypatch.setattr(dsr, "SHOT_FILE", tmp_path / ".logs" / "shot.png")
    monkeypatch.setattr(dsr, "OTP_LAST_ASK", tmp_path / "otp_last_ask.json")
    monkeypatch.setattr(dsr, "OTP_REQUEST", tmp_path / "otp_request.json")
    monkeypatch.setattr(dsr, "OTP_REPLY", tmp_path / "otp.json")
    monkeypatch.setattr(dsr, "notify_mac", lambda title, body: None)
    return env


class Resp:
    def __init__(self, status: int, body: Any = None, bad_json: bool = False) -> None:
        self.status_code, self._body, self._bad = status, body, bad_json

    def json(self) -> Any:
        if self._bad:
            raise ValueError("not JSON")
        return self._body


class FakeClock:
    def __init__(self) -> None:
        self.t, self.sleeps = 1000.0, []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


def _post_script(*answers: Any):
    """A fake httpx.post that plays `answers` in order (an exception instance is raised) and records each call."""
    calls: list[dict[str, Any]] = []
    queue = list(answers)

    def post(url: str, json: Any = None, timeout: float = 0) -> Resp:
        calls.append({"url": url, "json": json, "timeout": timeout})
        answer = queue.pop(0) if len(queue) > 1 else queue[0]                  # the last answer repeats
        if isinstance(answer, Exception):
            raise answer
        return answer
    return post, calls


# ── P13: .env writes (also master-controller's /password and /userid) ─────────────────────────────────────────

def _old_write_env_value(env: Path, key: str, value: str) -> None:
    """The pre-fix writer, verbatim logic (negative control)."""
    content = env.read_text()
    new, n = re.subn(rf"^{re.escape(key)}=.*$", f"{key}={value}", content, flags=re.MULTILINE)
    env.write_text(new if n else content.rstrip() + f"\n{key}={value}\n")


@pytest.mark.parametrize("value", ["Secret #2026", "x$y", "$HOME", "it's #x", 'say "hi" #1', " lead", "trail ",
                                   "a#b", "p@ss w0rd!#$%^&*()"])
def test_write_env_value_round_trips_through_every_reader(files: Path, value: str) -> None:
    dsr.write_env_value("ICICI_PASSWORD", value)
    assert dsr.read_env_file()["ICICI_PASSWORD"] == value                    # this script's own parser
    got = dotenv_values(files)                                                # python-dotenv: services, controller
    assert got["ICICI_PASSWORD"] == value
    assert got["EXECUTION_LIVE_ALLOWED"] == "0" and got["TELEGRAM_BOT_TOKEN"] == "123:abc"
    assert stat.S_IMODE(files.stat().st_mode) == 0o600


def test_the_old_writer_lost_part_of_the_password(tmp_path: Path) -> None:
    """Negative control: /password 'Secret #2026' through the old raw writer reads back as 'Secret'."""
    env = tmp_path / ".env"
    env.write_text(ENV_TEXT)
    _old_write_env_value(env, "ICICI_PASSWORD", "Secret #2026")
    assert dotenv_values(env)["ICICI_PASSWORD"] == "Secret"


def test_write_env_value_creates_a_missing_env_0600(files: Path) -> None:
    files.unlink()
    old_umask = os.umask(0o022)
    try:
        dsr.write_env_value("ICICI_SESSION_TOKEN", "55667788")
    finally:
        os.umask(old_umask)
    assert files.read_text() == "ICICI_SESSION_TOKEN=55667788\n" and stat.S_IMODE(files.stat().st_mode) == 0o600


def test_write_env_value_keeps_one_line_per_key_and_the_rest(files: Path) -> None:
    dsr.write_env_value("ICICI_SESSION_TOKEN", "new-token")
    assert files.read_text() == ENV_TEXT.replace("ICICI_SESSION_TOKEN=old-token", "ICICI_SESSION_TOKEN=new-token")


@pytest.mark.parametrize(("key", "value", "why"), [("ICICI_PASSWORD", "a${HOME}b", "expand"),
                                                   ("ICICI_PASSWORD", "x\nEXECUTION_LIVE_ALLOWED=1", "line break"),
                                                   ("ICICI_SESSION_TOKEN", "tok #x", "unquoted"),
                                                   ("EXECUTION_LIVE_ALLOWED", "1", "cannot be changed")])
def test_write_env_value_refuses_and_leaves_env_alone(files: Path, key: str, value: str, why: str) -> None:
    with pytest.raises(ValueError, match=why) as exc:
        dsr.write_env_value(key, value)
    assert files.read_text() == ENV_TEXT and value not in str(exc.value)


def test_loading_the_writer_does_not_touch_sys_path(files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """master-controller imports this script: services/ui-api must not land on its sys.path (main.py, db.py, ...
    there would shadow other modules). The module is loaded fresh here, by file path, under a private name."""
    monkeypatch.delitem(sys.modules, "_suryadhana_icici_admin", raising=False)
    before = list(sys.path)
    dsr.write_env_value("ICICI_PASSWORD", "x")
    assert sys.path == before
    assert sys.modules["_suryadhana_icici_admin"].__file__ == str(dsr.ICICI_ADMIN_FILE)


# ── P3: the hand-off to ui-api ────────────────────────────────────────────────────────────────────────────────

def test_handoff_retries_until_ui_api_answers() -> None:
    clock = FakeClock()
    post, calls = _post_script(httpx.ConnectError("refused"), Resp(503), Resp(200, {"connected": True}))
    body, why = dsr.handoff_to_ui_api("tok", budget_s=120, post=post, clock=clock, sleep=clock.sleep)
    assert body == {"connected": True} and why == "" and len(calls) == 3 and clock.sleeps == [2.0, 4.0]
    assert calls[0]["url"].endswith("/api/positions/session-token")
    assert calls[0]["json"] == {"token": "tok", "fresh_login": True}


def test_handoff_gives_up_after_about_two_minutes() -> None:
    clock = FakeClock()
    post, calls = _post_script(httpx.ConnectError("refused"))
    body, why = dsr.handoff_to_ui_api("tok", budget_s=120, post=post, clock=clock, sleep=clock.sleep)
    assert body is None and "ConnectError" in why and f"after {len(calls)} attempt(s)" in why
    assert len(calls) >= 6 and sum(clock.sleeps) <= 120                       # retried for the whole budget
    assert all(c["timeout"] <= 120 for c in calls)


def test_handoff_does_not_retry_a_refusal() -> None:
    clock = FakeClock()
    post, calls = _post_script(Resp(400, {"detail": "bad"}))
    body, why = dsr.handoff_to_ui_api("tok", budget_s=120, post=post, clock=clock, sleep=clock.sleep)
    assert body is None and why == "HTTP 400 (refused)" and len(calls) == 1 and clock.sleeps == []


def test_handoff_retries_a_garbled_answer() -> None:
    clock = FakeClock()
    post, calls = _post_script(Resp(200, bad_json=True), Resp(200, {"connected": False, "error_kind": "network"}))
    body, _ = dsr.handoff_to_ui_api("tok", budget_s=120, post=post, clock=clock, sleep=clock.sleep)
    assert body == {"connected": False, "error_kind": "network"} and len(calls) == 2


def test_the_handoff_budget_shrinks_when_the_login_took_long(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dsr, "_time_left", lambda: 400.0)
    assert dsr.handoff_budget_s() == 120.0
    monkeypatch.setattr(dsr, "_time_left", lambda: 100.0)                     # OTP reply came late
    assert dsr.handoff_budget_s() == 40.0
    monkeypatch.setattr(dsr, "_time_left", lambda: 10.0)
    assert dsr.handoff_budget_s() == dsr.UI_API_HANDOFF_MIN_S


def test_apply_token_via_ui_api(files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dsr, "handoff_to_ui_api", lambda token, budget_s: ({"connected": True, "error": None}, ""))
    monkeypatch.setattr(dsr, "push_token_to_data_service", lambda *a, **k: pytest.fail("ui-api pushes it"))
    out = dsr.apply_token("new-token", "k", "s")
    assert out["via"] == "ui-api" and out["connected"] is True and files.read_text() == ENV_TEXT


def test_apply_token_falls_back_to_env_and_sends_the_token_to_data_service(files: Path,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dsr, "handoff_to_ui_api", lambda token, budget_s: (None, "ConnectError after 7 attempt(s)"))
    sent: list[dict[str, Any]] = []

    def post(url: str, json: Any = None, timeout: float = 0) -> Resp:
        sent.append({"url": url, "json": json})
        return Resp(200, {"provider": "ICICIBreezeProvider", "connected": True})
    monkeypatch.setattr(dsr.httpx, "post", post)
    monkeypatch.setattr(dsr, "check_token", lambda *a, **k: pytest.fail("data-service already confirmed it"))
    out = dsr.apply_token("new-token", "k", "s")
    assert out["via"] == ".env" and out["connected"] is True and "7 attempt" in out["why"]
    assert dotenv_values(files)["ICICI_SESSION_TOKEN"] == "new-token"
    assert sent == [{"url": f"{dsr.DATA_SERVICE}/provider/configure",
                     "json": {"api_key": "k", "api_secret": "s", "session_token": "new-token"}}]


def test_the_old_reconnect_body_kept_the_stale_token() -> None:
    """Negative control: data-service's /provider/configure fills a missing field from its own environment, so the
    controller's json={} reconnect reuses the token data-service already had (services/data-service/main.py)."""
    src = (ROOT / "services" / "data-service" / "main.py").read_text(encoding="utf-8")
    assert ('req.session_token if req.session_token is not None else os.environ.get("ICICI_SESSION_TOKEN", "")'
            in src)


def test_apply_token_fallback_checks_the_token_when_data_service_is_down(files: Path,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dsr, "handoff_to_ui_api", lambda token, budget_s: (None, "ReadTimeout after 1 attempt(s)"))
    monkeypatch.setattr(dsr, "push_token_to_data_service", lambda *a, **k: {"ok": False, "connected": False})
    monkeypatch.setattr(dsr, "_time_left", lambda: 300.0)
    monkeypatch.setattr(dsr, "check_token", lambda k, s, t: ("valid", ""))
    assert dsr.apply_token("new-token", "k", "s")["connected"] is True
    monkeypatch.setattr(dsr, "check_token", lambda k, s, t: ("expired", "rejected"))
    out = dsr.apply_token("new-token", "k", "s")
    assert out["connected"] is False and out["error_kind"] == "expired"


def test_apply_token_fallback_never_overruns_the_controller_timeout(files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dsr, "handoff_to_ui_api", lambda token, budget_s: (None, "ConnectError"))
    monkeypatch.setattr(dsr, "push_token_to_data_service", lambda *a, **k: {"ok": False, "connected": False})
    monkeypatch.setattr(dsr, "_time_left", lambda: 60.0)
    monkeypatch.setattr(dsr, "check_token", lambda *a: pytest.fail("a 3-try check could outlast the 480 s kill"))
    out = dsr.apply_token("new-token", "k", "s")
    assert out["connected"] is False and dotenv_values(files)["ICICI_SESSION_TOKEN"] == "new-token"


# ── main(): outcomes reported to master-controller ───────────────────────────────────────────────────────────

def _run_main(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "argv", ["daily_session_refresh.py", *argv])
    monkeypatch.setattr(dsr, "read_env_file", lambda: {"ICICI_API_KEY": "k", "ICICI_API_SECRET": "s",
                                                      "ICICI_SESSION_TOKEN": "old-token", "ICICI_CLIENT_ID": "AD1",
                                                      "ICICI_PASSWORD": "pw"})
    monkeypatch.setattr(dsr, "read_secret", lambda name, env: env.get(name, ""))   # never the Keychain
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ICICI_TOTP_SECRET"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit) as exc:
        dsr.main()
    line = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("RESULT ")][-1]
    return int(exc.value.code), json.loads(line[len("RESULT "):])


def test_a_fallback_login_is_reported_as_a_warning(files: Path, monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    notes: list[str] = []
    monkeypatch.setattr(dsr, "notify_mac", lambda title, body: notes.append(title))
    monkeypatch.setattr(dsr, "check_token", lambda k, s, t: ("expired", "expired"))
    monkeypatch.setattr(dsr, "browser_login", lambda *a, **k: "new-token")
    monkeypatch.setattr(dsr, "apply_token", lambda t, k, s: {"via": ".env", "connected": True, "why": "ConnectError",
                                                              "data_service": {"connected": True}})
    rc, res = _run_main(monkeypatch, capsys, "--headless")
    assert rc == 0 and res["status"] == "refreshed" and res["outcome"] == "warning" and res["via"] == ".env"
    assert res["detail"].startswith("WARNING:") and ".env only" in res["detail"] and "live quotes: on" in res["detail"]
    assert notes == ["SuryaDhana · ICICI token saved to .env only"]
    assert json.loads(dsr.CACHE_FILE.read_text())["outcome"] == "warning"


def test_a_normal_login_is_plain_success(files: Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    """Negative control for the warning: the ui-api path keeps the old 'refreshed' detail."""
    monkeypatch.setattr(dsr, "check_token", lambda k, s, t: ("expired", "expired"))
    monkeypatch.setattr(dsr, "browser_login", lambda *a, **k: "new-token")
    monkeypatch.setattr(dsr, "apply_token", lambda t, k, s: {"via": "ui-api", "connected": True, "error": None})
    rc, res = _run_main(monkeypatch, capsys, "--headless")
    assert (rc, res["status"], res["outcome"], res["detail"]) == (0, "refreshed", "ok", "logged in, token applied via ui-api")


def test_an_icici_outage_does_not_start_a_login(files: Path, monkeypatch: pytest.MonkeyPatch,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(dsr, "check_token", lambda k, s, t: ("network", "Couldn't reach ICICI's API server"))
    monkeypatch.setattr(dsr, "browser_login", lambda *a, **k: pytest.fail("no login (and no OTP) during an outage"))
    rc, res = _run_main(monkeypatch, capsys, "--headless")
    assert rc == dsr.EXIT_RETRY and res["status"] == "unreachable" and res["error_kind"] == "network"
    assert "unreachable" in res["detail"]


def test_an_expired_token_still_logs_in(files: Path, monkeypatch: pytest.MonkeyPatch,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    """Negative control for the outage test."""
    logins: list[int] = []
    monkeypatch.setattr(dsr, "check_token", lambda k, s, t: ("expired", "expired"))
    monkeypatch.setattr(dsr, "browser_login", lambda *a, **k: logins.append(1) or "new-token")
    monkeypatch.setattr(dsr, "apply_token", lambda t, k, s: {"via": "ui-api", "connected": True, "error": None})
    rc, _ = _run_main(monkeypatch, capsys, "--headless")
    assert rc == 0 and logins == [1]


# ── P4: check_token ──────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("probe", "state"), [
    ({"connected": True}, "valid"),
    ({"connected": False, "error_kind": "session_expired", "error": "expired"}, "expired"),
    ({"connected": False, "error_kind": "network", "error": "unreachable"}, "network"),
    ({"connected": False, "error_kind": "credentials", "error": "key"}, "credentials"),
    ({"connected": False, "error_kind": "other", "error": "?"}, "unknown"),
])
def test_check_token_classifies(probe: dict[str, Any], state: str) -> None:
    assert dsr.check_token("k", "s", "tok", probe=lambda *a: probe)[0] == state


def test_check_token_classifies_a_raised_sdk_error() -> None:
    def boom(*a: Any) -> dict[str, Any]:
        raise Exception("Unexpected error: Max retries exceeded with url (ConnectTimeoutError)")  # noqa: TRY002
    assert dsr.check_token("k", "s", "tok", probe=boom)[0] == "network"


def test_token_works_cannot_tell_an_outage_from_an_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control: the bool token_works() (what main() used) is False for both, which is why a network
    outage used to start a login; main() now branches on check_token()'s state."""
    for state in ("network", "expired"):
        monkeypatch.setattr(dsr, "check_token", lambda k, s, t, _state=state: (_state, ""))
        assert dsr.token_works("k", "s", "tok") is False


def test_check_token_without_settings_never_calls_breeze() -> None:
    def no(*a: Any) -> dict[str, Any]:
        raise AssertionError("no Breeze call")
    assert dsr.check_token("", "s", "tok", probe=no)[0] == "credentials"
    assert dsr.check_token("k", "s", "", probe=no)[0] == "expired"
