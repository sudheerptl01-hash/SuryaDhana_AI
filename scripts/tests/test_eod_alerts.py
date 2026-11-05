"""EOD alert routing (15 Oct 2026 incident): a finished pipeline with failed non-fatal steps must
WARN — never report a clean "OK" — and a clean run reports OK."""
import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import master_controller as mc  # noqa: E402


class _Alerts:
    def __init__(self):
        self.sent = []

    async def info(self, title, body):
        self.sent.append(("info", title, body))

    async def warning(self, title, body):
        self.sent.append(("warning", title, body))

    async def critical(self, title, body):
        self.sent.append(("critical", title, body))


def _wire(monkeypatch, result):
    alerts = _Alerts()

    async def fake_job(job, path, body):
        return result

    async def no_check(job):
        return None

    @asynccontextmanager
    async def no_track(job):
        yield

    monkeypatch.setattr(mc, "_alerts", alerts)
    monkeypatch.setattr(mc, "_run_data_job", fake_job)
    monkeypatch.setattr(mc, "_check_dataset_freshness", no_check)
    monkeypatch.setattr(mc, "_track", no_track)
    monkeypatch.setattr(mc, "DATA_JOBS_ENABLED", True)
    return alerts


def test_failed_ml_build_warns_instead_of_reporting_ok(monkeypatch):
    alerts = _wire(monkeypatch, {
        "refresh": {}, "bhavcopy": {"rows_written": 3511},
        "build": {"error": "OutOfMemoryException: Out of Memory Error: failed to allocate 16.0 MiB"},
    })
    asyncio.run(mc.eod_data_pipeline())
    kinds = [a[0] for a in alerts.sent]
    assert kinds == ["warning"], alerts.sent
    assert "build: OutOfMemoryException" in alerts.sent[0][2]


def test_clean_run_reports_ok(monkeypatch):
    alerts = _wire(monkeypatch, {"refresh": {}, "bhavcopy": {"rows_written": 3511},
                                 "build": {"feature_rows": 1, "label_rows": 1, "feature_date_range": ["a", "b"]}})
    asyncio.run(mc.eod_data_pipeline())
    assert [a[0] for a in alerts.sent] == ["info"]
