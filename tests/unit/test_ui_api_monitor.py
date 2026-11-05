import asyncio
import importlib.util
from pathlib import Path
import pytest


def _load_monitor_module():
    file_path = Path(__file__).resolve().parents[2] / "services" / "ui-api" / "routers" / "monitor.py"
    spec = importlib.util.spec_from_file_location("ui_api_monitor", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DummyResponse:
    def __init__(self, status_code: int = 200, data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text or ""

    def json(self):
        return self._data


class DummyAsyncClient:
    def __init__(self, *args, **kwargs):
        self._response = DummyResponse(
            status_code=200,
            data={"symbol": "NIFTY", "record": {"symbol": "NIFTY", "payload": '{"price": 25000}'}}
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str):
        return self._response


def test_get_live_nifty_proxies_data_service(monkeypatch):
    module = _load_monitor_module()
    module.DATA_SVC = "http://localhost:8001"
    monkeypatch.setattr(module.httpx, "AsyncClient", DummyAsyncClient)

    result = asyncio.run(module.get_live_nifty())

    assert result["symbol"] == "NIFTY"
    assert result["record"]["symbol"] == "NIFTY"
    assert result["record"]["payload"] == '{"price": 25000}'
