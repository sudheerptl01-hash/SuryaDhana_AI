import importlib.util
import sys
import asyncio
from pathlib import Path
import tempfile
import os

import pytest

service_path = str(Path(__file__).resolve().parents[2] / "services" / "data-service")
sys.path.insert(0, service_path)

from storage.duckdb_store import DuckDBStore


def _load_data_service_main():
    file_path = Path(service_path) / "main.py"
    spec = importlib.util.spec_from_file_location("data_service_main", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_duckdb_live_quote_insert_and_retrieve():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_live_quotes.duckdb")
        store = DuckDBStore(db_path)

        rows_written = store.upsert_live_quote(
            symbol="NIFTY",
            ts="2026-01-01T12:00:00Z",
            payload='{"price": 20000}',
        )

        assert rows_written == 1

        latest = store.get_latest_live_quotes(limit=5)
        assert len(latest) == 1
        assert latest[0]["symbol"] == "NIFTY"
        assert "payload" in latest[0]
        assert latest[0]["payload"] == '{"price": 20000}'
        assert latest[0]["ts"].startswith("2026-01-01")


def test_live_nifty_endpoint_returns_latest_quote():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_live_quotes_endpoint.duckdb")
        store = DuckDBStore(db_path)
        store.upsert_live_quote(
            symbol="NIFTY",
            ts="2026-01-01T12:00:00Z",
            payload='{"price": 20000}',
        )

        data_service_main = _load_data_service_main()
        # Sync handler (FastAPI runs it in the threadpool so DB-lock waits never block the loop)
        result = data_service_main.get_live_nifty(store=store)

        assert result["symbol"] == "NIFTY"
        assert result["record"]["symbol"] == "NIFTY"
        assert result["record"]["payload"] == '{"price": 20000}'
