"""scripts/tests: shared guards.

M33 (6 Nov, O-OPS): master_controller._track compares a job's catalogued datasets before and after each run with a GET of
data-service /db/data-health. That read is armed only by lifespan(), which several tests run — so every test here runs
with the check OFF (no GET to a live :8001 from a test), and the tests of the check turn it on with their own fake.
The same for the post-EOD alert round (alerts_after: a POST to ui-api from a background task)."""
from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def _no_dataset_check_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    mc = sys.modules.get("master_controller")
    if mc is not None and hasattr(mc, "JOB_DATASET_CHECK"):
        monkeypatch.setattr(mc, "JOB_DATASET_CHECK", False)
    # the post-EOD alert round (PLAN 2.3) is a background task: off unless a test drives it with its own fake, so no
    # test's ui-api call outlives the test's transport
    if mc is not None and hasattr(mc, "ALERTS_ENGINE_ENABLED"):
        monkeypatch.setattr(mc, "ALERTS_ENGINE_ENABLED", False)
    # the per-start catch-up plan and the in-flight table are module state: each test starts from empty ones
    for name in ("_CATCHUP_PLAN", "_RUNNING", "_status_marks"):
        if mc is not None and isinstance(getattr(mc, name, None), dict):
            monkeypatch.setattr(mc, name, {})
    if mc is not None and isinstance(getattr(mc, "_CATCHUP_SCHEDULED", None), set):
        monkeypatch.setattr(mc, "_CATCHUP_SCHEDULED", set())
    if mc is not None and isinstance(getattr(mc, "_DATASET_CHECK", None), dict):
        monkeypatch.setattr(mc, "_DATASET_CHECK", {"armed": False, "at": 0.0, "ids": None})
