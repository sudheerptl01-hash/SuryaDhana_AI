"""errors.py + app-level handler (F2.4/A2): detail stays a string, structured block rides beside it."""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from errors import CODES, code_for_status, degraded, fail  # noqa: E402


def _app_with_handler() -> FastAPI:
    # mirror main.py's handler wiring without importing the full app (no live deps in CI)
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from errors import code_for_status, error_block

    app = FastAPI()

    @app.exception_handler(StarletteHTTPException)
    async def handler(request, exc):
        d = exc.detail
        if isinstance(d, dict) and "code" in d and "message" in d:
            block = error_block(d["code"], str(d["message"]), d.get("hint"))
            message = str(d["message"])
        else:
            message = d if isinstance(d, str) else str(d)
            block = error_block(code_for_status(exc.status_code), message)
        return JSONResponse({"detail": message, "error": block}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.get("/new")
    def new_style():
        fail(404, "not_found", "Unknown ticker ZZZ", hint="Try the GO bar search")

    @app.get("/legacy")
    def legacy_style():
        raise HTTPException(status_code=503, detail="data-service unreachable: boom")

    @app.get("/framework-404")
    def noop():
        return {}
    return app


def test_fail_keeps_detail_string_and_adds_error_block():
    c = TestClient(_app_with_handler())
    r = c.get("/new")
    assert r.status_code == 404
    body = r.json()
    assert body["detail"] == "Unknown ticker ZZZ"                     # legacy renderers keep working
    assert body["error"] == {"code": "not_found", "message": "Unknown ticker ZZZ",
                             "hint": "Try the GO bar search"}


def test_legacy_string_raise_gets_wrapped_additively():
    c = TestClient(_app_with_handler())
    r = c.get("/legacy")
    assert r.status_code == 503
    body = r.json()
    assert body["detail"].startswith("data-service unreachable")
    assert body["error"]["code"] == "state" and "hint" not in body["error"]


def test_framework_404_also_carries_the_contract():
    c = TestClient(_app_with_handler())
    r = c.get("/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert isinstance(r.json()["detail"], str)


def test_degraded_preserves_legacy_keys_and_adds_error_info():
    legacy = {"connected": False, "error": "session expired", "positions": []}
    out = degraded(legacy, "state", "session expired", hint="Send /login on Telegram")
    assert out["error"] == "session expired"                          # legacy string untouched
    assert out["ok"] is False
    assert out["error_info"]["code"] == "state" and out["error_info"]["hint"].startswith("Send /login")
    assert out["positions"] == []


def test_code_mapping_and_enum():
    assert code_for_status(404) == "not_found"
    assert code_for_status(401) == code_for_status(403) == "unauthorized"
    assert code_for_status(422) == "invalid"
    assert code_for_status(503) == "state"
    assert code_for_status(502) == "upstream_down"
    assert code_for_status(500) == "internal"
    assert set(CODES) == {"not_found", "upstream_down", "degraded", "unauthorized", "invalid", "state", "internal"}


def test_live_app_handler_is_wired():
    main_src = (Path(__file__).resolve().parents[1] / "main.py").read_text()
    assert "_error_contract_handler" in main_src and "StarletteHTTPException" in main_src
