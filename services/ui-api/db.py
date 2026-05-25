"""Shared DuckDB connection helper for UI API routes."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
import duckdb

# Support both Docker (via env var) and local development
DB_PATH = os.environ.get("DATABASE_URL", str(Path(__file__).resolve().parent.parent.parent / "data" / "market.duckdb"))


@contextmanager
def get_conn():
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        yield conn
    finally:
        conn.close()
