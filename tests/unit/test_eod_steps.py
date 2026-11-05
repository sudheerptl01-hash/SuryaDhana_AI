"""EOD step isolation (15 Oct 2026 incident: the ML build OOM'd and skipped the NSE bhavcopy)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "data-service"))
import eod_steps  # noqa: E402


class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, msg, **kw):
        self.lines.append(("warning", msg, kw))

    def error(self, msg, **kw):
        self.lines.append(("error", msg, kw))


def _boom():
    raise MemoryError("Out of Memory Error: failed to allocate 16.0 MiB")


def test_every_step_runs_in_order_even_after_a_failure():
    ran = []
    log = _Log()
    out = eod_steps.run_steps([
        ("refresh", lambda: ran.append("refresh") or {"ok": 1}, True),
        ("build", lambda: (ran.append("build"), _boom()), False),
        ("bhavcopy", lambda: ran.append("bhavcopy") or {"rows_written": 3511}, False),
    ], log)
    assert ran == ["refresh", "build", "bhavcopy"]                 # the failure skipped nothing
    assert out["bhavcopy"] == {"rows_written": 3511}
    assert out["build"]["error"].startswith("MemoryError: Out of Memory")
    assert log.lines[0][0] == "warning"                            # non-fatal -> warning, no raise


def test_fatal_failure_still_runs_the_rest_then_raises():
    ran = []
    with pytest.raises(eod_steps.EodStepsFailed) as ei:
        eod_steps.run_steps([
            ("refresh", _boom, True),
            ("bhavcopy", lambda: ran.append("bhavcopy") or {}, False),
        ], _Log())
    assert ran == ["bhavcopy"]                                     # data still landed
    assert ei.value.failed == ["refresh"] and "refresh: MemoryError" in str(ei.value)
    assert ei.value.results["bhavcopy"] == {}


def test_soft_failures_lists_only_errored_steps():
    res = {"refresh": {"ok": 1}, "build": {"error": "X"}, "nse_events": {"failures": []}}
    assert eod_steps.soft_failures(res) == {"build": "X"}


def test_main_pipeline_runs_market_data_before_the_ml_build():
    """Structural guard: in data-service main.py the ML build is the LAST, non-fatal step."""
    src = (ROOT / "services" / "data-service" / "main.py").read_text()
    body = src[src.index("    def _pipeline(progress) -> dict:"):]
    body = body[: body.index("], logger)")]
    steps = re.findall(r'^\s*\("(\w+)",.*,\s*(True|False)\),?\s*$', body, flags=re.MULTILINE)
    names = [n for n, _ in steps]
    assert names[-1] == "build" and dict(steps)["build"] == "False"
    for data_step in ("bhavcopy", "nse_positions", "market_monitor", "nse_events"):
        assert names.index(data_step) < names.index("build")
