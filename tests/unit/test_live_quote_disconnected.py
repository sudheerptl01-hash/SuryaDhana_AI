"""data-service /live/quote: no broker session → a plain 'not connected' answer, not a 500."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "data-service"))

import os as _os  # noqa: E402
_ENV_BEFORE = dict(_os.environ)
import main as data_service  # noqa: E402  (exports the project .env into os.environ at import)
for _k in set(_os.environ) - set(_ENV_BEFORE):    # the 6 Nov flaky-test fix: no .env leak into later tests
    del _os.environ[_k]


class _Disconnected:
    def is_connected(self) -> bool:
        return False

    def get_live_quote(self, ticker):  # pragma: no cover - must not be called
        raise AssertionError("called the broker without a session")


class _Connected:
    def is_connected(self) -> bool:
        return True

    def get_live_quote(self, ticker):
        return {"ltp": 101.5}


def test_live_quote_without_session_is_not_an_error():
    out = data_service.get_live_quote("ABDL", live=_Disconnected())
    assert out["quote"] is None and out["connected"] is False and "not connected" in out["reason"]


def test_live_quote_with_session_returns_the_quote():
    assert data_service.get_live_quote("ABDL", live=_Connected()) == {"ticker": "ABDL", "quote": {"ltp": 101.5},
                                                                     "connected": True}
