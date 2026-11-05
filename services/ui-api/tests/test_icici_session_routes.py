"""ICICI session routes (desktop review round 4a, F4-API).

P4: /connection-status and /open-positions (also /summary, /sector-exposure, /trade-history on their error paths)
carry an additive ``error_kind``: 'expired' | 'network' | 'credentials' | 'unknown' (null when connected), so the
desktop shell and BRIEF can say "ICICI unreachable" instead of "expired: send /login" during a network outage.
P16: a pasted token that ICICI rejects no longer replaces the token in use (os.environ and .env stay as they were).
Breeze is never called: the probe and the client builder are stubbed; .env is a scratch file.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import icici_admin
from routers import positions as pos

NETWORK = icici_admin.classify_breeze_error("Max retries exceeded with url: /breezeapi (ConnectTimeoutError)")[1]
EXPIRED = icici_admin.classify_breeze_error("Session key is expired.")[1]
KEY_BAD = icici_admin.classify_breeze_error("Public Key does not exist.")[1]
PROBE_BY_TOKEN: dict[str, dict[str, Any]] = {
    "good-token": {"connected": True, "account_name": "TEST USER", "customer_id": "AD000001", "attempts": 1},
    "old-token": {"connected": False, "error_kind": "session_expired", "error": EXPIRED},
    "bad-token": {"connected": False, "error_kind": "session_expired", "error": EXPIRED},
    "net-token": {"connected": False, "error_kind": "network", "error": NETWORK},
    "key-token": {"connected": False, "error_kind": "credentials", "error": KEY_BAD},
    "odd-token": {"connected": False, "error_kind": "other", "error": "Unexpected Breeze response: {}"},
}
ENV_TEXT = "A=1\nICICI_API_KEY=k\nICICI_API_SECRET=s\nICICI_SESSION_TOKEN=old-token\nB=2\n"


@pytest.fixture
def breeze(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    env = tmp_path / ".env"
    env.write_text(ENV_TEXT)
    monkeypatch.setattr(icici_admin, "find_env_file", lambda: env)
    monkeypatch.setenv("ICICI_API_KEY", "k")
    monkeypatch.setenv("ICICI_API_SECRET", "s")
    monkeypatch.setenv("ICICI_SESSION_TOKEN", "old-token")
    state: dict[str, Any] = {"env": env, "probed": [], "propagated": []}

    def probe(api_key: str, api_secret: str, token: str) -> dict[str, Any]:
        state["probed"].append(token)
        return dict(PROBE_BY_TOKEN[token])

    async def propagate(**kwargs: Any) -> dict[str, Any]:
        state["propagated"].append(kwargs["session_token"])
        return {"data_service": {"ok": True}}

    async def no_status() -> dict[str, Any]:
        return {}

    monkeypatch.setattr(pos, "probe_breeze_connection", probe)
    monkeypatch.setattr(pos, "propagate_runtime_config", propagate)
    monkeypatch.setattr(pos, "collect_backend_status", no_status)
    pos._invalidate_breeze_state()
    app = FastAPI()
    app.include_router(pos.router, prefix="/api/positions")
    state["client"] = TestClient(app)
    yield state
    pos._invalidate_breeze_state()


# ── P4: error_kind ────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("token", "kind"), [("good-token", None), ("old-token", "expired"), ("net-token", "network"),
                                             ("key-token", "credentials"), ("odd-token", "unknown")])
def test_connection_status_carries_the_error_kind(breeze: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
                                                 token: str, kind: str | None) -> None:
    monkeypatch.setenv("ICICI_SESSION_TOKEN", token)
    body = breeze["client"].get("/api/positions/connection-status").json()
    assert body["error_kind"] == kind and body["connected"] is (kind is None)
    assert body["error"] == PROBE_BY_TOKEN[token].get("error")                     # existing fields unchanged


def test_a_network_failure_is_distinguishable_from_an_expired_token(breeze: dict[str, Any],
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control: the fields the shell read before (connected, needs_session_refresh) are identical for an
    outage and an expired token; only error_kind tells them apart."""
    seen = {}
    for token in ("net-token", "old-token"):
        monkeypatch.setenv("ICICI_SESSION_TOKEN", token)
        body = breeze["client"].get("/api/positions/connection-status").json()
        seen[token] = body
    old_fields = [{k: seen[t][k] for k in ("connected", "needs_session_refresh")} for t in ("net-token", "old-token")]
    assert old_fields[0] == old_fields[1] == {"connected": False, "needs_session_refresh": True}
    assert (seen["net-token"]["error_kind"], seen["old-token"]["error_kind"]) == ("network", "expired")


@pytest.mark.parametrize(("unset", "kind"), [("ICICI_API_KEY", "credentials"), ("ICICI_SESSION_TOKEN", "expired")])
def test_missing_settings_have_a_kind_too(breeze: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
                                          unset: str, kind: str) -> None:
    monkeypatch.delenv(unset)
    status = pos._runtime_status()
    assert status["error_kind"] == kind and breeze["probed"] == []


@pytest.mark.parametrize(("message", "kind"), [("Max retries exceeded (ConnectTimeoutError)", "network"),
                                               ("Session key is expired.", "expired"),
                                               ("Public Key does not exist.", "credentials"),
                                               ("something else", "unknown")])
def test_open_positions_carries_the_error_kind(breeze: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
                                               message: str, kind: str) -> None:
    def failing_build(api_key: str, api_secret: str, token: str):
        raise_kind, text = icici_admin.classify_breeze_error(message)
        return None, text, raise_kind
    monkeypatch.setattr(pos, "_build_breeze_client", failing_build)
    body = pos.get_open_positions()
    assert body["connected"] is False and body["error_kind"] == kind and body["positions"] == []
    assert body["error"] == icici_admin.classify_breeze_error(message)[1]            # existing message unchanged
    hint = body["error_info"]["hint"]
    assert ("not a login problem" in hint) is (kind == "network") and ("/login" in hint) is (kind != "network")
    for route in (pos.get_position_summary, pos.get_sector_exposure):
        assert route()["error_kind"] == kind


def test_open_positions_without_credentials(breeze: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ICICI_API_SECRET")
    assert pos.get_open_positions()["error_kind"] == "credentials"
    monkeypatch.setenv("ICICI_API_SECRET", "s")
    monkeypatch.delenv("ICICI_SESSION_TOKEN")
    assert pos.get_open_positions()["error_kind"] == "expired"


def test_a_session_ended_mid_read_is_expired(breeze: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    class Dead:
        def get_portfolio_holdings(self, **kw: Any) -> dict[str, Any]:
            return {"Status": 401, "Error": "Session key is expired."}
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (Dead(), None))
    body = pos.get_open_positions()
    assert body["error_kind"] == "expired" and body["needs_session_refresh"] is True


def test_open_positions_success_shape_is_unchanged(breeze: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    class Empty:
        def get_portfolio_holdings(self, **kw: Any) -> dict[str, Any]:
            return {"Status": 500, "Error": "No Data Found"}
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (Empty(), None))
    assert pos.get_open_positions() == {"connected": True, "positions": [], "count": 0}


# ── P16: a rejected paste keeps the token in use ──────────────────────────────────────────────────────────────

def _token_line(env: Path) -> str:
    return next(line for line in env.read_text().splitlines() if line.startswith("ICICI_SESSION_TOKEN="))


def test_a_rejected_paste_keeps_the_token_in_use(breeze: dict[str, Any]) -> None:
    import os
    r = breeze["client"].post("/api/positions/session-token", json={"token": "http://127.0.0.1/?apisession=bad-token"})
    body = r.json()
    assert r.status_code == 200 and body["connected"] is False and body["kept_previous_token"] is True
    assert body["persisted"] is False and body["error_kind"] == "expired" and "was not saved" in body["error"]
    assert breeze["probed"] == ["bad-token"]                                       # the new token WAS checked
    assert _token_line(breeze["env"]) == "ICICI_SESSION_TOKEN=old-token"           # .env untouched
    assert breeze["env"].read_text() == ENV_TEXT
    assert os.environ["ICICI_SESSION_TOKEN"] == "old-token" and breeze["propagated"] == []


def test_a_fresh_login_token_is_saved_even_if_the_check_fails(breeze: dict[str, Any]) -> None:
    """Negative control (and the 08:00 job's path): with fresh_login the same rejected token replaces the old one,
    as every paste did before (ICICI ended the previous session when it issued this token)."""
    import os
    body = breeze["client"].post("/api/positions/session-token", json={"token": "bad-token", "fresh_login": True}).json()
    assert body["connected"] is False and body["persisted"] is True and "kept_previous_token" not in body
    assert _token_line(breeze["env"]) == "ICICI_SESSION_TOKEN=bad-token" and os.environ["ICICI_SESSION_TOKEN"] == "bad-token"


@pytest.mark.parametrize(("token", "kind"), [("net-token", "network"), ("key-token", "credentials"), ("odd-token", "unknown")])
def test_a_failure_that_says_nothing_about_the_token_still_saves_it(breeze: dict[str, Any], token: str, kind: str) -> None:
    body = breeze["client"].post("/api/positions/session-token", json={"token": token}).json()
    assert body["connected"] is False and body["persisted"] is True and body["error_kind"] == kind
    assert _token_line(breeze["env"]) == f"ICICI_SESSION_TOKEN={token}"


def test_a_good_paste_is_saved_and_pushed(breeze: dict[str, Any]) -> None:
    body = breeze["client"].post("/api/positions/session-token", json={"token": "good-token"}).json()
    assert body["connected"] is True and body["error_kind"] is None and body["persisted"] is True
    assert _token_line(breeze["env"]) == "ICICI_SESSION_TOKEN=good-token" and breeze["propagated"] == ["good-token"]
    # the fresh check is kept for the token now in use: the next status poll needs no second Breeze login
    breeze["client"].get("/api/positions/connection-status")
    assert breeze["probed"] == ["good-token"]


def test_a_rejected_paste_restores_the_status_of_the_token_in_use(breeze: dict[str, Any]) -> None:
    first = breeze["client"].get("/api/positions/connection-status").json()          # old-token: expired, cached
    breeze["client"].post("/api/positions/session-token", json={"token": "bad-token"})
    again = breeze["client"].get("/api/positions/connection-status").json()
    assert breeze["probed"] == ["old-token", "bad-token"]                            # no extra login for old-token
    assert first["error_kind"] == again["error_kind"] == "expired" and again["has_session_token"] is True


def test_a_paste_is_always_checked_fresh(breeze: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """A cached answer for the same token is never reused by the paste route (the old invalidate-then-check)."""
    monkeypatch.setenv("ICICI_SESSION_TOKEN", "good-token")
    breeze["client"].get("/api/positions/connection-status")
    breeze["client"].post("/api/positions/session-token", json={"token": "good-token"})
    assert breeze["probed"] == ["good-token", "good-token"]


def test_a_quoted_token_is_refused_before_anything_changes(breeze: dict[str, Any]) -> None:
    """P13: scripts read ICICI_SESSION_TOKEN raw, so a token that would need quoting in .env is refused with a 400
    (nothing checked, nothing saved), and the token itself is never echoed."""
    import os
    r = breeze["client"].post("/api/positions/session-token", json={"token": '"55667788"'})
    assert r.status_code == 400 and "must fit unquoted" in r.text and "55667788" not in r.text
    assert "surrounding quotes" in r.json()["detail"]["hint"]
    assert breeze["probed"] == [] and breeze["env"].read_text() == ENV_TEXT and os.environ["ICICI_SESSION_TOKEN"] == "old-token"


# ── persisted_reason: why a save did not reach .env (round 3 review, minor) ───────────────────────────────────

def test_a_refused_env_write_says_why_by_key_name_only(breeze: dict[str, Any]) -> None:
    breeze["env"].write_text(ENV_TEXT + "DERIVED=${ICICI_SESSION_TOKEN}\nDERIVED_KEY=${ICICI_API_KEY}\n")
    body = breeze["client"].post("/api/positions/session-token", json={"token": "net-token"}).json()
    assert body["persisted"] is False and body["persisted_reason"] == "DERIVED would change"
    assert "net-token" not in body["persisted_reason"] and "old-token" not in body["persisted_reason"]
    creds = breeze["client"].post("/api/positions/credentials", json={"api_key": "k2", "api_secret": "s2"}).json()
    assert creds["persisted"] is False and creds["persisted_reason"] == "DERIVED_KEY would change"


def test_a_saved_write_has_no_persisted_reason(breeze: dict[str, Any]) -> None:
    body = breeze["client"].post("/api/positions/session-token", json={"token": "good-token"}).json()
    assert body["persisted"] is True and body["persisted_reason"] is None
    body = breeze["client"].post("/api/positions/session-token", json={"token": "net-token"}).json()
    assert body["persisted"] is True and body["persisted_reason"] is None
