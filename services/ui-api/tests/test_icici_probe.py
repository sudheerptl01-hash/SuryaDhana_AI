"""Breeze login probe: network failures are retried and explained; login failures are not retried."""
import sys
import types

import icici_admin

NET = ("Unexpected error: HTTPSConnectionPool(host='api.icicidirect.com', port=443): Max retries exceeded with url: "
       "/breezeapi/api/v1/customerdetails (Caused by ConnectTimeoutError(..., 'Connection to api.icicidirect.com "
       "timed out. (connect timeout=10)'))")


def _fake_breeze(monkeypatch, failures: list[str]):
    calls = {"n": 0}

    class FakeBreeze:
        def __init__(self, api_key):
            pass

        def generate_session(self, api_secret, session_token):
            calls["n"] += 1
            if failures:
                raise Exception(failures.pop(0))

        def get_customer_details(self, api_session):
            return {"Status": 200, "Success": {"idirect_user_name": "TEST USER", "idirect_userid": "AD000001"}}

    monkeypatch.setitem(sys.modules, "breeze_connect", types.SimpleNamespace(BreezeConnect=FakeBreeze))
    return calls


def test_network_timeouts_are_retried_then_connect(monkeypatch):
    calls = _fake_breeze(monkeypatch, [NET, NET])
    waits: list[float] = []
    out = icici_admin.probe_breeze_connection("k", "s", "12345678", sleep=waits.append)
    assert out["connected"] and out["attempts"] == 3 and calls["n"] == 3 and waits == [2.0, 5.0]


def test_persistent_network_failure_is_explained_not_dumped(monkeypatch):
    _fake_breeze(monkeypatch, [NET, NET, NET])
    out = icici_admin.probe_breeze_connection("k", "s", "12345678", sleep=lambda s: None)
    assert not out["connected"] and out["error_kind"] == "network"
    assert "not your session token" in out["error"] and "HTTPSConnectionPool" not in out["error"]


def test_expired_session_fails_fast_without_retry(monkeypatch):
    calls = _fake_breeze(monkeypatch, ["Unexpected error: Session key is expired.", NET])
    out = icici_admin.probe_breeze_connection("k", "s", "12345678", sleep=lambda s: None)
    assert calls["n"] == 1 and out["error_kind"] == "session_expired" and "log in again" in out["error"]


def test_sdk_messages_are_classified():
    for text, kind in (("Unexpected error: Public Key does not exist.", "credentials"),
                       ("Unexpected error: Could not authenticate credentials. Please check api key.", "credentials"),
                       ("Unexpected error: Could not authenticate credentials. Please check session key.", "session_expired"),
                       ("Unexpected error: Session key is expired.", "session_expired"),
                       (NET, "network")):
        assert icici_admin.classify_breeze_error(text)[0] == kind, text
