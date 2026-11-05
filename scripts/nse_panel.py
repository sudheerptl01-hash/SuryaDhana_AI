"""Compatibility shim: the panel code lives in shared/nse_panel.py (used by research and the Decision Desk)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.nse_panel import *  # noqa: E402,F401,F403
from shared.nse_panel import (  # noqa: E402,F401
    EQUITY_SERIES, STANDARD_FACTORS, _snap, adjust, corporate_action_factors, load_panel, pick_equity_rows,
    survivorship_report,
)
