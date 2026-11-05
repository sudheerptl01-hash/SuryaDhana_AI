from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _support import NOW, make_store


@pytest.fixture
def store(tmp_path: Path):
    s = make_store(tmp_path)
    yield s
    s.close()


@pytest.fixture
def now():
    return NOW


@pytest.fixture(autouse=True)
def _breeze_cache_in_tmp(tmp_path: Path, monkeypatch):
    """fetch_mcx_master writes a new master to the Breeze SDK cache: never the real data/cache/breeze in a test."""
    from gold import ingest_india

    target = tmp_path / "breeze_cache" / "SecurityMaster.zip"
    monkeypatch.setattr(ingest_india, "_breeze_cache_file", lambda: target)
    return target
