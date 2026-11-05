""".env writes from the Broker tab cannot inject new lines (fix-round-1 adversarial check on C2-security-03).

The PAPER ONLY opt-in (EXECUTION_LIVE_ALLOWED) and the guard settings (GUARD_*) live in .env, and POST
/api/positions/credentials and /session-token write .env. A value with a line break used to add a NEW line
(``abc\\nEXECUTION_LIVE_ALLOWED=1``) that load_dotenv applies at the next ui-api start. Now every key and value
is validated before os.environ or the file changes. Unit tests on icici_admin plus the REAL routes."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

UI_API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI_API_DIR))

import icici_admin  # noqa: E402

ENV_TEXT = "A=1\nICICI_API_KEY=old-key\nICICI_API_SECRET=old-secret\nB=2\n"
INJECT = "EXECUTION_LIVE_ALLOWED=1"


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    env = tmp_path / ".env"
    env.write_text(ENV_TEXT)
    monkeypatch.setattr(icici_admin, "find_env_file", lambda: env)
    return env


BAD_VALUES = {
    "LF": f"abc\n{INJECT}", "CR": f"abc\r{INJECT}", "CRLF": f"abc\r\n{INJECT}", "NUL": "abc\x00def",
    "VT": "abc\x0bdef", "FF": "abc\x0cdef", "FS": "abc\x1cdef", "NEL": f"abc\x85{INJECT}", "DEL": "abc\x7f",
    "LINE SEP": f"abc\u2028{INJECT}", "PARA SEP": f"abc\u2029{INJECT}", "ZWSP": "abc\u200bdef", "BOM": "\ufeffabc",
    "ESC": "abc\x1b[31m", "TOO LONG": "x" * (icici_admin.MAX_ENV_VALUE_CHARS + 1),
}


@pytest.mark.parametrize("name", sorted(BAD_VALUES))
def test_unsafe_values_are_refused_and_the_file_is_untouched(env_file: Path, name: str) -> None:
    value = BAD_VALUES[name]
    with pytest.raises(icici_admin.EnvValueError) as exc:
        icici_admin.persist_env_updates({"ICICI_API_KEY": value}, allowed_keys=icici_admin.ICICI_ENV_KEYS)
    assert env_file.read_text() == ENV_TEXT
    assert "ICICI_API_KEY" in str(exc.value) and value not in str(exc.value) and "abc" not in str(exc.value)


def test_an_injected_line_would_otherwise_have_been_read_back_by_dotenv(tmp_path: Path) -> None:
    """What the validation prevents: the raw line format turns an embedded LF into a second .env entry."""
    from dotenv import dotenv_values
    raw = tmp_path / "raw.env"
    raw.write_text(f"ICICI_API_KEY={BAD_VALUES['LF']}\n")
    assert dotenv_values(raw).get("EXECUTION_LIVE_ALLOWED") == "1"
    assert icici_admin.env_value_problem(BAD_VALUES["LF"]) == "contains a line break"


@pytest.mark.parametrize("value", ["AbC123xyz", "p@ss w0rd!#$%^&*()_+-=[]{}|;':,./<>?~`", "ünïcødé-ok", "", "a=b=c"])
def test_ordinary_values_are_written(env_file: Path, value: str) -> None:
    out = icici_admin.persist_env_updates({"ICICI_PASSWORD": value}, allowed_keys=icici_admin.ICICI_ENV_KEYS)
    assert out["persisted"] is True
    assert env_file.read_text().splitlines()[-1] == f"ICICI_PASSWORD={value}"


@pytest.mark.parametrize("key", ["EXECUTION_LIVE_ALLOWED", "EXECUTION_MODE", "GUARD_ALLOW_REMOTE_WRITES",
                                 "GUARD_ALLOWED_HOSTS", "UI_API_DOCS", "UI_API_ENV_FILE", "PYTEST_CURRENT_TEST",
                                 "FORWARDED_ALLOW_IPS", "PREFS_DB", "PAPER_TRADES_DB", "MONITOR_WS_MAX"])
def test_posture_and_security_keys_are_never_written(env_file: Path, key: str) -> None:
    with pytest.raises(icici_admin.EnvValueError, match="cannot be changed from the terminal"):
        icici_admin.persist_env_updates({key: "1"})
    assert env_file.read_text() == ENV_TEXT


@pytest.mark.parametrize("key", ["", "A=B", "A\nB", "1ABC", "A B", "ICICI-KEY", "K" * 200])
def test_malformed_keys_are_refused(env_file: Path, key: str) -> None:
    with pytest.raises(icici_admin.EnvValueError, match="not a valid .env key name"):
        icici_admin.persist_env_updates({key: "1"})
    assert env_file.read_text() == ENV_TEXT


def test_the_allowlist_limits_the_routes_to_the_icici_keys(env_file: Path) -> None:
    with pytest.raises(icici_admin.EnvValueError, match="OTHER_KEY cannot be changed"):
        icici_admin.persist_env_updates({"ICICI_API_KEY": "k", "OTHER_KEY": "v"}, allowed_keys=icici_admin.ICICI_ENV_KEYS)
    assert env_file.read_text() == ENV_TEXT                        # all-or-nothing: the valid key was not written
    assert icici_admin.ICICI_ENV_KEYS == {"ICICI_API_KEY", "ICICI_API_SECRET", "ICICI_CLIENT_ID", "ICICI_PASSWORD",
                                          "ICICI_SESSION_TOKEN", "ICICI_TOTP_SECRET"}   # TOTP: GOLD program PLAN §g


def test_existing_one_line_per_key_behaviour_is_kept(env_file: Path) -> None:
    env_file.write_text("A=1\nICICI_SESSION_TOKEN=old\nB=2\nICICI_SESSION_TOKEN=old\n")
    icici_admin.persist_env_updates({"ICICI_SESSION_TOKEN": "new"}, allowed_keys=icici_admin.ICICI_ENV_KEYS)
    assert env_file.read_text().splitlines() == ["A=1", "ICICI_SESSION_TOKEN=new", "B=2"]


# ── the real routes ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ui_main(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    release = tmp_path_factory.mktemp("dist") / "release"
    release.mkdir()
    (release / "index.html").write_text("<!doctype html><title>SuryaDhana</title>")
    mp = pytest.MonkeyPatch()
    mp.setenv("UI_DIST_DIR", str(release))
    import dotenv
    mp.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    try:
        spec = importlib.util.spec_from_file_location("ui_api_main_env_injection", UI_API_DIR / "main.py")
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture
def routes(ui_main: ModuleType, env_file: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    pos = sys.modules["routers.positions"]
    calls: dict[str, Any] = {"propagated": 0}

    async def no_backend(**k: Any) -> dict[str, Any]:
        calls["propagated"] += 1
        return {}

    async def no_status() -> dict[str, Any]:
        return {}
    monkeypatch.setattr(pos, "_invalidate_breeze_state", lambda: None)            # no Breeze, no network
    monkeypatch.setattr(pos, "_runtime_status", lambda *a, **k: {"connected": False, "error": "stubbed", "error_kind": "unknown",
                                                                  "has_session_token": True, "needs_api_credentials": False})
    monkeypatch.setattr(pos, "propagate_runtime_config", no_backend)
    monkeypatch.setattr(pos, "collect_backend_status", no_status)
    for key in icici_admin.ICICI_ENV_KEYS:
        monkeypatch.setenv(key, f"env-{key}")                                     # restored after the test
    monkeypatch.delenv("EXECUTION_LIVE_ALLOWED", raising=False)
    calls["client"] = TestClient(ui_main.app)
    return calls


@pytest.mark.parametrize("field", ["api_key", "api_secret", "client_id", "password"])
def test_credentials_route_refuses_an_injected_line(routes: dict[str, Any], env_file: Path, field: str) -> None:
    body = {"api_key": "good-key", "api_secret": "good-secret", "client_id": "C1", "password": "pw"}
    body[field] = f"x\n{INJECT}"
    r = routes["client"].post("/api/positions/credentials", json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid"
    assert INJECT not in r.text and "line break" in r.json()["detail"]
    assert env_file.read_text() == ENV_TEXT                                       # nothing written
    assert os.environ["ICICI_API_KEY"] == "env-ICICI_API_KEY"                     # nothing changed in-process
    assert "EXECUTION_LIVE_ALLOWED" not in os.environ


def test_credentials_route_still_saves_good_values(routes: dict[str, Any], env_file: Path) -> None:
    r = routes["client"].post("/api/positions/credentials",
                              json={"api_key": " new-key ", "api_secret": "new-secret", "password": "p w!"})
    assert r.status_code == 200 and r.json()["persisted"] is True
    lines = env_file.read_text().splitlines()
    assert "ICICI_API_KEY=new-key" in lines and "ICICI_API_SECRET=new-secret" in lines and "ICICI_PASSWORD=p w!" in lines
    assert os.environ["ICICI_API_KEY"] == "new-key"


@pytest.mark.parametrize("token", [f"123456\u2028{INJECT}", f"123456\x00{INJECT}", f"apisession=123\x00{INJECT}"])
def test_session_token_route_refuses_an_injected_line(routes: dict[str, Any], env_file: Path, token: str) -> None:
    r = routes["client"].post("/api/positions/session-token", json={"token": token})
    assert r.status_code == 400 and "ICICI_SESSION_TOKEN" in r.json()["detail"]
    assert env_file.read_text() == ENV_TEXT
    assert os.environ["ICICI_SESSION_TOKEN"] == "env-ICICI_SESSION_TOKEN"


def test_session_token_route_still_extracts_and_saves(routes: dict[str, Any], env_file: Path) -> None:
    r = routes["client"].post("/api/positions/session-token",
                              json={"token": "http://127.0.0.1/?apisession=55667788&x=1"})
    assert r.status_code == 200 and r.json()["persisted"] is True
    assert "ICICI_SESSION_TOKEN=55667788" in env_file.read_text().splitlines()


def test_a_redirect_url_with_a_separator_keeps_only_the_token(routes: dict[str, Any], env_file: Path) -> None:
    # extract_session_token stops at whitespace (NEL included), so only the token part is ever written
    r = routes["client"].post("/api/positions/session-token", json={"token": f"apisession=123\x85{INJECT}"})
    assert r.status_code == 200
    assert "ICICI_SESSION_TOKEN=123" in env_file.read_text().splitlines() and INJECT not in env_file.read_text()
