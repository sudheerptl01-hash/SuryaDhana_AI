"""Shared helpers for the gold test suites (tests/gold, tests/gold_replay): sys.path for the data-service package,
the research sample folders, a temp-file DuckDB store factory and a fake HTTP client. Not a test module."""
from __future__ import annotations

# ruff: noqa: DTZ001
# (timestamps are UTC-naive by the store's convention)
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA_SERVICE = ROOT / "services" / "data-service"
for p in (str(ROOT), str(DATA_SERVICE)):
    if p not in sys.path:
        sys.path.insert(0, p)

REPORTS = ROOT / "reports" / "gold_program"
G_COT = REPORTS / "G-COT" / "data"
G_CME = REPORTS / "G-CME" / "samples"
G_MACRO = REPORTS / "G-MACRO"
G_PHYS = REPORTS / "G-PHYSICAL" / "samples"
G_INDIA = REPORTS / "G-INDIA" / "scratch"
G_KITCO = REPORTS / "G-KITCO" / "scratch" / "bodies"
G_STUDY = REPORTS / "G-STUDY" / "data"
FIXTURES = ROOT / "tests" / "gold_replay" / "fixtures"
NOW = datetime(2026, 10, 26, 5, 0)          # UTC-naive, 10:30 IST on the build day


def make_store(tmp_path: Path) -> Any:
    """A DuckDBStore on a temp file (never data/market.duckdb); the gold DDL runs through the store's own schema init."""
    from storage.duckdb_store import DuckDBStore

    return DuckDBStore(str(tmp_path / "gold_test.duckdb"))


def read(path: Path, *, binary: bool = False) -> Any:
    return path.read_bytes() if binary else path.read_text(encoding="utf-8", errors="ignore")


class FakeResponse:
    def __init__(self, status: int = 200, text: str = "", content: bytes | None = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers = headers or {}

    def json(self) -> Any:
        import json

        return json.loads(self.text)


class FakeHttp:
    """Routes URLs to canned responses; records every call; refuses nothing (the allowlist is tested separately)."""

    def __init__(self, routes: dict[str, FakeResponse] | None = None, default: FakeResponse | None = None) -> None:
        self.routes = routes or {}
        self.default = default or FakeResponse(404, "")
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _match(self, url: str) -> FakeResponse:
        for key, resp in self.routes.items():
            if key in url:
                return resp
        return self.default

    def get(self, url: str, **kw: Any) -> FakeResponse:
        self.calls.append((url, kw))
        return self._match(url)

    def post(self, url: str, **kw: Any) -> FakeResponse:
        self.calls.append((url, kw))
        return self._match(url)

    def stream_to_file(self, url: str, path: str, **kw: Any) -> int:
        self.calls.append((url, kw))
        body = self._match(url).content
        Path(path).write_bytes(body)
        return len(body)
