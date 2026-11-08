"""UN Comtrade backfill: month maths, the empty-answer trap, and the never-overwrite rule.

Comtrade is the only machine-readable official source for India's monthly gold imports (SOURCES.md F14). Its preview
endpoint answers a THROTTLED call with HTTP 200 and an empty data list rather than an error, which is how a silent hole
would get into the series — so that path has its own test.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gold_india_imports_comtrade as c  # noqa: E402


def test_month_range_and_point_in_time_dates():
    assert c.months("2026-01", "2026-03") == ["202601", "202602", "202603"]
    assert c.months("2025-11", "2026-02") == ["202511", "202512", "202601", "202602"]
    assert c.months("2026-03", "2026-01") == []          # negative control: a reversed range yields nothing
    assert c.period_to_date("202602").isoformat() == "2026-02-28"   # the row is dated the month it covers
    assert c.period_to_date("202412").isoformat() == "2024-12-31"


def test_an_empty_answer_is_re_asked_before_it_is_believed():
    calls = []

    class _R:
        status_code = 200

        def __init__(self, rows):
            self._rows = rows

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": self._rows}

    class _C:
        def get(self, url, **kw):
            calls.append(kw["params"]["period"])
            # throttled first, real on the re-ask — exactly what Comtrade did on 8 Nov 2026
            return _R([] if len(calls) == 1 else [{"primaryValue": 9.61e9, "netWgt": 100000.0}])

    c.PACE_S = 0
    got = c.fetch(_C(), "202509")
    assert len(calls) == 2, "an empty answer must be re-asked once"
    assert got is not None and round(got[0], 2) == 9.61


def test_a_genuinely_unfiled_month_still_returns_none():
    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": []}

    class _C:
        def get(self, url, **kw):
            return _R()

    c.PACE_S = 0
    assert c.fetch(_C(), "209912") is None      # negative control: twice empty means not filed


def test_the_tolerance_only_flags_a_real_divergence():
    # a press figure and the final filing differ a little; 10 % is the line
    assert c.TOLERANCE_PCT == 10.0
    for stored_v, filed in ((5.439, 5.439), (1.8, 1.84), (9.61, 9.70)):
        assert abs(stored_v - filed) / filed * 100 <= c.TOLERANCE_PCT
    assert abs(1.8 - 51.64) / 51.64 * 100 > c.TOLERANCE_PCT     # the aggregate that nearly got stored


def test_the_job_is_registered_monthly_outside_the_freeze_windows():
    src = (Path(__file__).resolve().parents[1] / "master_controller.py").read_text()
    i = src.index('id="india_imports_comtrade"')
    block = src[max(0, i - 400):i]
    assert "day=20" in block and "hour=11" in block and "minute=45" in block
    body = src[src.index("async def india_imports_comtrade"):src.index("async def india_imports_watch")]
    assert "GOLD_JOBS_ENABLED" in body
    assert "Nothing was overwritten." in body        # a divergence is reported, never applied
