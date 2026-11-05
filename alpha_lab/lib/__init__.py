"""Vendored shared code (see ORIGINS.md). Alias so intra-copy `from shared...` imports resolve here."""
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
if str(_here.parent) not in sys.path:
    sys.path.insert(0, str(_here.parent))
import importlib

sys.modules.setdefault("shared", importlib.import_module("lib"))
