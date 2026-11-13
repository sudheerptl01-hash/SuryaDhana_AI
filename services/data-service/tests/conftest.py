"""data-service unit tests: put the service dir and the repo root on sys.path (the service imports
``shared.*`` from the root and its own modules flat, exactly as uvicorn runs it)."""
from __future__ import annotations

import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
ROOT = SERVICE.parents[1]
for p in (str(ROOT), str(SERVICE)):
    if p not in sys.path:
        sys.path.insert(0, p)
