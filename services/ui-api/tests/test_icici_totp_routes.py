"""ICICI auto-login TOTP routes (GOLD program PLAN §g, gate T6): /api/positions/totp/status · /totp/preview · /totp ·
DELETE /totp.

Every test is offline: the Keychain probe, pgrep and the login script are stubbed; .env is a scratch file (0600); the TOTP
clock is frozen so the RFC 6238 test vector (secret "12345678901234567890", t = 59 → 287082) is reproducible.

Binding secrecy rules checked here: the secret is never echoed by any route (only `preview.code`, which the phone shows
anyway); a bad key is a 400 whose body never contains the input; a save is refused without a confirmation code that matches
the current or previous 30-second window; the saved line is bare base32, exactly one line, with .env's mode preserved; the
allowlist refuses the key when it is absent (regression for icici_admin.ICICI_ENV_KEYS); the delete writes an empty value
and reports a Keychain copy instead of touching it.
"""

from __future__ import annotations

import base64
import os
import stat
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import icici_admin  # noqa: E402
from routers import positions as pos  # noqa: E402
from shared.icici_login import parse_totp_secret, totp  # noqa: E402

RFC_SECRET_B32 = base64.b32encode(b"12345678901234567890").decode()  # GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ
RFC_CODE_T59 = "287082"
RFC_CODE_T29 = "755224"
ENV_TEXT = "A=1\nICICI_API_KEY=k\nICICI_API_SECRET=s\nICICI_SESSION_TOKEN=old-token\nB=2\n"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    env_file = tmp_path / ".env"
    env_file.write_text(ENV_TEXT)
    env_file.chmod(0o600)
    monkeypatch.setattr(icici_admin, "find_env_file", lambda: env_file)
    monkeypatch.setenv("UI_API_ENV_FILE", str(env_file))
    monkeypatch.delenv("ICICI_TOTP_SECRET", raising=False)
    monkeypatch.delenv("ICICI_AUTO_LOGIN", raising=False)
    state: dict[str, Any] = {"env": env_file, "keychain": False, "running": False, "clock": 59.0}
    monkeypatch.setattr(pos, "_keychain_has_totp", lambda: state["keychain"])
    monkeypatch.setattr(pos, "_login_running", lambda: state["running"])
    monkeypatch.setattr(pos, "_totp_clock", lambda: state["clock"])
    (tmp_path / "data").mkdir()
    return state


def _client() -> TestClient:
    """The routes on a bare app with main.py's error contract (errors.fail → {detail: str, error: {code, message, hint}})."""
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from errors import code_for_status, error_block

    app = FastAPI()

    @app.exception_handler(StarletteHTTPException)
    async def _contract(request: Any, exc: StarletteHTTPException) -> JSONResponse:  # mirror of main._error_contract_handler
        d = exc.detail
        if isinstance(d, dict) and "code" in d and "message" in d:
            block, message = error_block(d["code"], str(d["message"]), d.get("hint")), str(d["message"])
        else:
            message = d if isinstance(d, str) else str(d)
            block = error_block(code_for_status(exc.status_code), message)
        return JSONResponse({"detail": message, "error": block}, status_code=exc.status_code)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(pos.router, prefix="/api/positions")
    return TestClient(app)


def _env_lines(env: dict[str, Any]) -> list[str]:
    return [ln for ln in env["env"].read_text().split("\n") if ln.startswith("ICICI_TOTP_SECRET=")]


# ── preview ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_preview_returns_the_rfc_6238_vector_and_stores_nothing(env: dict[str, Any]) -> None:
    c = _client()
    r = c.post("/api/positions/totp/preview", json={"secret": RFC_SECRET_B32})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "valid": True,
        "digits": 6,
        "period": 30,
        "algorithm": "sha1",
        "length": 32,
        "code": RFC_CODE_T59,
        "seconds_left": 1,
    }
    assert RFC_SECRET_B32 not in r.text and "ICICI_TOTP_SECRET" not in env["env"].read_text()
    assert os.environ.get("ICICI_TOTP_SECRET") is None
    env["clock"] = 29.0
    assert c.post("/api/positions/totp/preview", json={"secret": RFC_SECRET_B32}).json()["code"] == RFC_CODE_T29


def test_preview_accepts_spaced_lowercase_and_otpauth_forms(env: dict[str, Any]) -> None:
    c = _client()
    spaced = " ".join(RFC_SECRET_B32.lower()[i : i + 4] for i in range(0, 32, 4))
    assert c.post("/api/positions/totp/preview", json={"secret": spaced}).json()["code"] == RFC_CODE_T59
    uri = f"otpauth://totp/ICICI%20Direct:AD000001?secret={RFC_SECRET_B32}&issuer=ICICI%20Direct&digits=6&period=30"
    r = c.post("/api/positions/totp/preview", json={"secret": uri})
    assert r.status_code == 200 and r.json()["code"] == RFC_CODE_T59 and r.json()["length"] == 32


@pytest.mark.parametrize(
    "bad", ["not-a-key!!", "189", "otpauth://totp/x?secret=%%%", "", "ABCDEFGH1", "otpauth://totp/x?secret=GEZD&digits=12"]
)
def test_bad_secret_is_a_400_that_never_echoes_the_input(env: dict[str, Any], bad: str) -> None:
    c = _client()
    r = c.post("/api/positions/totp/preview", json={"secret": bad})
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["detail"] == pos.TOTP_BAD_SECRET and body["error"]["code"] == "invalid"
    if bad.strip():
        assert bad not in r.text and bad.strip("!") not in r.text.replace(pos.TOTP_BAD_SECRET, "")
    r2 = c.post("/api/positions/totp", json={"secret": bad, "confirm_code": "000000"})
    assert r2.status_code == 400 and (not bad.strip() or bad not in r2.text)


# ── save ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_save_is_refused_without_a_matching_confirmation(env: dict[str, Any]) -> None:
    c = _client()
    for confirm in ("", "000000", "123456", RFC_CODE_T29[::-1]):
        r = c.post("/api/positions/totp", json={"secret": RFC_SECRET_B32, "confirm_code": confirm})
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == pos.TOTP_BAD_CONFIRM and RFC_SECRET_B32 not in r.text
    assert _env_lines(env) == [] and os.environ.get("ICICI_TOTP_SECRET") is None
    # a code from two windows back is not accepted either
    env["clock"] = 119.0
    r = c.post("/api/positions/totp", json={"secret": RFC_SECRET_B32, "confirm_code": RFC_CODE_T59})
    assert r.status_code == 400


def test_save_with_the_current_or_previous_window_writes_one_line_and_keeps_0600(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _client()
    env["clock"] = 89.0  # window 2 (60–89 s): previous window is t = 59 → 287082
    r = c.post("/api/positions/totp", json={"secret": RFC_SECRET_B32.lower(), "confirm_code": "287 082"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] is True and body["persisted"] is True and body["source"] == "env" and body["env_mode"] == "0600"
    assert body["env_mode_warning"] is None and body["keychain_present"] is False
    assert RFC_SECRET_B32 not in r.text
    lines = _env_lines(env)
    assert lines == [f"ICICI_TOTP_SECRET={RFC_SECRET_B32}"]  # bare base32, exactly one line
    assert stat.S_IMODE(env["env"].stat().st_mode) == 0o600
    assert env["env"].read_text().startswith(ENV_TEXT)  # the other lines are untouched
    assert os.environ["ICICI_TOTP_SECRET"] == RFC_SECRET_B32
    monkeypatch.delenv("ICICI_TOTP_SECRET")
    # saving again (current window this time) replaces the line instead of appending a duplicate
    r2 = c.post(
        "/api/positions/totp", json={"secret": RFC_SECRET_B32, "confirm_code": totp(parse_totp_secret(RFC_SECRET_B32), 89.0)}
    )
    assert r2.status_code == 200 and _env_lines(env) == [f"ICICI_TOTP_SECRET={RFC_SECRET_B32}"]
    monkeypatch.delenv("ICICI_TOTP_SECRET")


def test_save_warns_when_env_is_not_0600(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    env["env"].chmod(0o644)
    r = _client().post("/api/positions/totp", json={"secret": RFC_SECRET_B32, "confirm_code": RFC_CODE_T59})
    assert r.status_code == 200 and r.json()["env_mode"] == "0644" and "chmod 600" in r.json()["env_mode_warning"]
    assert stat.S_IMODE(env["env"].stat().st_mode) == 0o644  # the writer keeps the bits; the owner runs chmod
    monkeypatch.delenv("ICICI_TOTP_SECRET")


def test_allowlist_regression_the_key_must_be_in_icici_env_keys(env: dict[str, Any]) -> None:
    assert "ICICI_TOTP_SECRET" in icici_admin.ICICI_ENV_KEYS
    icici_admin.validate_env_updates({"ICICI_TOTP_SECRET": RFC_SECRET_B32}, icici_admin.ICICI_ENV_KEYS)
    without = icici_admin.ICICI_ENV_KEYS - {"ICICI_TOTP_SECRET"}
    with pytest.raises(icici_admin.EnvValueError, match="cannot be changed from the terminal"):
        icici_admin.validate_env_updates({"ICICI_TOTP_SECRET": RFC_SECRET_B32}, without)
    with pytest.raises(icici_admin.EnvValueError):
        icici_admin.persist_env_updates({"ICICI_TOTP_SECRET": RFC_SECRET_B32}, allowed_keys=without)
    assert _env_lines(env) == []


# ── status · delete ──────────────────────────────────────────────────────────────────────────────────────────────


def test_status_never_returns_the_secret_and_reveal_computes_the_code(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _client()
    s = c.get("/api/positions/totp/status").json()
    assert s["configured"] is False and s["source"] is None and s["env_mode"] == "0600" and s["env_mode_ok"] is True
    assert s["auto_login_enabled"] is True and s["login_running"] is False and s["otp_pending"] is False
    assert s["block"] == {"credentials": False, "totp": False} and s["next_run_ist"].endswith("T08:00+05:30")
    assert "security add-generic-password" in s["keychain_hint"] and "code" not in s
    monkeypatch.setenv("ICICI_TOTP_SECRET", RFC_SECRET_B32)
    s2 = c.get("/api/positions/totp/status", params={"reveal": 1})
    assert s2.json()["configured"] is True and s2.json()["source"] == "env" and s2.json()["code"] == RFC_CODE_T59
    assert RFC_SECRET_B32 not in s2.text
    assert "code" not in c.get("/api/positions/totp/status").json()
    env["keychain"] = True
    monkeypatch.delenv("ICICI_TOTP_SECRET")
    monkeypatch.setattr("shared.icici_login.read_secret", lambda name: RFC_SECRET_B32)
    s3 = c.get("/api/positions/totp/status", params={"reveal": 1})
    assert s3.json()["source"] == "keychain" and s3.json()["code"] == RFC_CODE_T59 and RFC_SECRET_B32 not in s3.text
    env["running"] = True
    assert c.get("/api/positions/totp/status").json()["login_running"] is True


def test_status_reads_the_last_login_and_the_block_files(env: dict[str, Any], tmp_path: Path) -> None:
    (tmp_path / ".session_cache.json").write_text(
        '{"at": "2026-10-23T08:08:00+05:30", "status": "refreshed", "detail": "via ui-api"}'
    )
    (tmp_path / ".icici_totp_block.json").write_text('{"fingerprint": "abc"}')
    (tmp_path / "data" / "icici_otp_request.json").write_text("{}")
    s = _client().get("/api/positions/totp/status").json()
    assert s["last_login"] == {"at": "2026-10-23T08:08:00+05:30", "status": "refreshed", "detail": "via ui-api"}
    assert s["block"]["totp"] is True and s["otp_pending"] is True


def test_delete_writes_an_empty_value_and_reports_the_keychain_copy(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    c = _client()
    assert c.post("/api/positions/totp", json={"secret": RFC_SECRET_B32, "confirm_code": RFC_CODE_T59}).status_code == 200
    env["keychain"] = True
    r = c.request("DELETE", "/api/positions/totp")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cleared"] is True and body["persisted"] is True and body["keychain_still_present"] is True
    assert body["keychain_hint"].startswith("security delete-generic-password") and RFC_SECRET_B32 not in r.text
    assert _env_lines(env) == ["ICICI_TOTP_SECRET="] and os.environ.get("ICICI_TOTP_SECRET") is None


def test_next_run_is_the_next_weekday_0800_or_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")
    assert pos._next_run_ist(datetime(2026, 10, 23, 9, 0, tzinfo=ist)) == "2026-10-26T08:00+05:30"  # Fri after 08:00 → Mon
    assert pos._next_run_ist(datetime(2026, 10, 26, 7, 59, tzinfo=ist)) == "2026-10-26T08:00+05:30"
    monkeypatch.setenv("ICICI_AUTO_LOGIN", "0")
    assert pos._next_run_ist(datetime(2026, 10, 26, 7, 59, tzinfo=ist)) is None


# ── shared/icici_login parsing cases the plan asks for (T6: 16-char key in groups of four; otpauth with %20) ────


def test_parse_totp_secret_sixteen_char_key_in_groups_of_four() -> None:
    spec = parse_totp_secret("abcd efgh ijkl mnop")
    assert spec.secret == base64.b32decode("ABCDEFGHIJKLMNOP") and spec.digits == 6 and spec.period == 30
    assert parse_totp_secret("ABCD-EFGH-IJKL-MNOP").secret == spec.secret
    assert totp(spec, 59).isdigit() and len(totp(spec, 59)) == 6


def test_parse_totp_secret_otpauth_with_percent_encoding() -> None:
    uri = "otpauth://totp/ICICI%20Direct:AD000001?secret=GEZD%20GNBV%20GY3T%20QOJQ%20GEZD%20GNBV%20GY3T%20QOJQ&issuer=ICICI%20Direct"
    spec = parse_totp_secret(uri)
    assert spec.secret == b"12345678901234567890" and totp(spec, 59) == RFC_CODE_T59
    with pytest.raises(ValueError):
        parse_totp_secret("otpauth://totp/x?secret=GEZD&algorithm=md5")


# ── event-loop purity: the blocking pieces (Keychain probe, pgrep, the .env write) run off the loop ──────────────


def test_totp_routes_keep_the_event_loop_free(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pos, "_keychain_has_totp", lambda: (time.sleep(0.5), False)[1])
    monkeypatch.setattr(pos, "_login_running", lambda: (time.sleep(0.3), False)[1])
    with _client() as c:
        done = threading.Event()

        def _heavy() -> None:
            try:
                c.get("/api/positions/totp/status")
                c.post("/api/positions/totp", json={"secret": RFC_SECRET_B32, "confirm_code": RFC_CODE_T59})
            finally:
                done.set()

        t = threading.Thread(target=_heavy, daemon=True)
        t.start()
        time.sleep(0.05)
        lat = []
        for _ in range(20):
            t0 = time.perf_counter()
            assert c.get("/health").status_code == 200
            lat.append(time.perf_counter() - t0)
        done.wait(timeout=10)
        t.join(timeout=10)
    lat.sort()
    assert lat[max(0, int(round(0.95 * len(lat))) - 1)] < 0.1
    monkeypatch.delenv("ICICI_TOTP_SECRET", raising=False)
