"""POST /api/client-errors (desktop review completeness-02, wave-2 contract K1), on the REAL main.app: one
structured 'client_error' log line per report, 8 KB cap, 30/min per process, credentials masked, nothing from
the request (headers, cookies, address) logged, foreign origins refused by the guard, no GET."""
from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

UI_API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI_API_DIR))

from routers import client_errors as ce

URL = "/api/client-errors"
SAME_ORIGIN = {"origin": "http://127.0.0.1:8010"}


@pytest.fixture(scope="module")
def ui_main(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    release = tmp_path_factory.mktemp("dist") / "release"
    release.mkdir()
    (release / "index.html").write_text("<!doctype html><title>SuryaDhana</title>")
    mp = pytest.MonkeyPatch()
    mp.setenv("UI_DIST_DIR", str(release))
    import dotenv
    mp.setattr(dotenv, "load_dotenv", lambda *a, **k: False)   # never read the live .env into this process
    try:
        spec = importlib.util.spec_from_file_location("ui_api_main_client_errors", UI_API_DIR / "main.py")
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture
def client(ui_main: ModuleType) -> TestClient:
    return TestClient(ui_main.app)


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(ce._JsonLineFormatter().format(r)) for r in self.records]


@pytest.fixture
def logged(monkeypatch: pytest.MonkeyPatch) -> _Capture:
    cap = _Capture()
    ce.log.addHandler(cap)
    monkeypatch.setattr(ce, "_limiter", ce._RateLimit())
    yield cap
    ce.log.removeHandler(cap)


def test_a_report_becomes_one_structured_log_line(client: TestClient, logged: _Capture) -> None:
    body = {"message": "TypeError: Cannot read properties of undefined (reading 'ltp')",
            "stack": "TypeError: ...\n    at Desk (app.js:1:2)", "tab": "desk", "build": "20261025-135500-0ae66db",
            "url": "http://127.0.0.1:8010/?tab=desk&sym=RELIANCE&utm=x#frag", "kind": "boundary", "extra": "ignored"}
    r = client.post(URL, json=body, headers={**SAME_ORIGIN, "cookie": "sid=SECRETCOOKIE", "user-agent": "UA-XYZ"})
    assert r.status_code == 204 and r.content == b"" and r.headers["x-client-error"] == "logged"
    (line,) = logged.lines()
    assert line["event"] == "client_error" and line["level"] == "warning" and line["component"] == "ui"
    assert line["message"] == body["message"] and line["tab"] == "desk" and line["build"] == body["build"]
    assert line["kind"] == "boundary" and line["stack"].startswith("TypeError: ...\n    at Desk")
    assert line["url"] == "/?tab=desk&sym=RELIANCE"                    # path + tab/sym only
    text = json.dumps(line)
    assert "SECRETCOOKIE" not in text and "UA-XYZ" not in text and "ignored" not in text and "127.0.0.1" not in text


def test_sendbeacon_text_plain_bodies_are_accepted(client: TestClient, logged: _Capture) -> None:
    r = client.post(URL, content=json.dumps({"message": "boom"}), headers={**SAME_ORIGIN, "content-type": "text/plain;charset=UTF-8"})
    assert r.status_code == 204 and logged.lines()[0]["message"] == "boom"
    assert logged.lines()[0]["kind"] == "unknown"


@pytest.mark.parametrize("content, ctype, status", [
    (b"message=boom", "application/x-www-form-urlencoded", 415),
    (b'{"message": "boom"}', "multipart/form-data; boundary=x", 415),
    (b'{"message": "boom"}', None, 415),
    (b"not json", "application/json", 422),
    (b'["message"]', "application/json", 422),
    (b'{"stack": "x"}', "application/json", 422),
    (b'{"message": "   "}', "application/json", 422),
    (b'{"message": "x", "tab": 5}', "application/json", 422),
    (b'{"message": "x", "kind": ["a"]}', "application/json", 422),
])
def test_malformed_reports_are_refused(client: TestClient, logged: _Capture, content: bytes, ctype: str | None,
                                       status: int) -> None:
    headers = dict(SAME_ORIGIN)
    if ctype:
        headers["content-type"] = ctype
    r = client.post(URL, content=content, headers=headers)
    assert r.status_code == status and r.json()["error"]["code"] == "invalid"
    assert logged.records == []


def test_the_body_is_capped_at_8_kb(client: TestClient, logged: _Capture) -> None:
    big = json.dumps({"message": "x", "stack": "y" * (ce.MAX_BODY_BYTES + 10)})
    assert client.post(URL, content=big, headers={**SAME_ORIGIN, "content-type": "application/json"}).status_code == 413

    def chunked():                                               # no Content-Length: counted while streaming
        yield big[:5000].encode()
        yield big[5000:].encode()
    r = client.post(URL, content=chunked(), headers={**SAME_ORIGIN, "content-type": "application/json"})
    assert r.status_code == 413 and logged.records == []


def test_fields_are_cut_cleaned_and_credentials_masked(client: TestClient, logged: _Capture) -> None:
    body = {"message": "fetch https://api.icicidirect.com/apiuser/login?api_key=AK123SECRET&x=1 failed\x00\x1b[31m",
            "stack": "Error: token=abc.def.ghi\nAuthorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload\n" + "s" * 5000,
            "url": "/api/positions/connection-status?session_token=999&tab=port", "kind": "Bad Kind!",
            "tab": "x" * 100}
    assert client.post(URL, json=body, headers=SAME_ORIGIN).status_code == 204
    (line,) = logged.lines()
    assert "AK123SECRET" not in line["message"] and "api_key=<redacted>" in line["message"]
    assert "\x00" not in line["message"] and "\x1b" not in line["message"]
    assert "abc.def.ghi" not in line["stack"] and "token=<redacted>" in line["stack"]
    assert "eyJhbGciOiJIUzI1NiJ9" not in line["stack"] and "Bearer <redacted>" in line["stack"]
    assert len(line["stack"]) == ce.FIELD_LIMITS["stack"] and "\n" in line["stack"]
    assert line["url"] == "/api/positions/connection-status?tab=port"
    assert line["kind"] == "unknown" and len(line["tab"]) == ce.FIELD_LIMITS["tab"]


def test_rate_limit_drops_silently_and_reports_the_count(client: TestClient, logged: _Capture,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    limiter = ce._RateLimit(limit=2, window_s=60.0)
    real_admit = limiter.admit
    monkeypatch.setattr(limiter, "admit", lambda now=None: real_admit(clock[0]))
    monkeypatch.setattr(ce, "_limiter", limiter)
    headers = []
    for _ in range(5):
        r = client.post(URL, json={"message": "storm"}, headers=SAME_ORIGIN)
        assert r.status_code == 204
        headers.append(r.headers["x-client-error"])
    assert headers == ["logged", "logged", "dropped", "dropped", "dropped"] and len(logged.records) == 2
    clock[0] = 61.0
    assert client.post(URL, json={"message": "after"}, headers=SAME_ORIGIN).headers["x-client-error"] == "logged"
    assert logged.lines()[-1]["dropped_since_last"] == 3


def test_default_rate_is_30_per_minute() -> None:
    rl = ce._RateLimit()
    assert [rl.admit(now=1.0)[0] for _ in range(31)] == [True] * 30 + [False]
    assert rl.admit(now=61.5) == (True, 1)


def test_cross_site_pages_cannot_report_and_there_is_no_get(client: TestClient, logged: _Capture) -> None:
    r = client.post(URL, content=b'{"message": "x"}', headers={"origin": "https://evil.example", "content-type": "text/plain"})
    assert r.status_code == 403 and logged.records == []
    assert client.post(URL, json={"message": "x"}, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    r = client.get(URL)
    assert r.status_code == 405 and r.json()["error"]["code"]
    assert client.post(URL, json={"message": "cli"}).status_code == 204          # no Origin: not a browser page
