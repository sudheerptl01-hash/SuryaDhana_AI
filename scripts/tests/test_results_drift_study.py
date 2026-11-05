"""Results drift study: bucket cut-offs and reaction-session timing (scripts/results_drift_study.py)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import results_drift_study as rds  # noqa: E402


@pytest.mark.parametrize("x,b", [(5.0, "strong up"), (12.0, "strong up"), (4.99, "up"), (2.0, "up"), (0.0, "flat"),
                                 (-2.0, "down"), (-4.99, "down"), (-5.0, "strong down"), (-30.0, "strong down")])
def test_bucket_edges(x, b):
    assert rds.bucket(x) == b


SESS = pd.bdate_range("2026-10-05", periods=6)          # Mon 5 … Mon 12 Oct


@pytest.mark.parametrize("ts,day,timing", [
    ("2026-10-07 11:00", "2026-10-07", "market hours"),
    ("2026-10-07 08:00", "2026-10-07", "pre-open"),
    ("2026-10-07 15:45", "2026-10-08", "after close"),
    ("2026-10-10 12:00", "2026-10-12", "after close"),       # Saturday release → Monday
])
def test_reaction_index(ts, day, timing):
    i, t = rds.reaction_index(pd.Timestamp(ts), SESS)
    assert SESS[i] == pd.Timestamp(day) and t == timing


def test_reaction_index_needs_a_prior_session():
    assert rds.reaction_index(pd.Timestamp("2026-10-04 12:00"), SESS)[0] is None      # before the first session
