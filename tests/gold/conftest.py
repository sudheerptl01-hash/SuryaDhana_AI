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
