"""Downtime recovery (19 Oct 2026 resilience review): heartbeat, missed-run counts, catch-up planning.
The stack was down 16→19 Oct; the scheduler skipped everything silently because it computes next runs
from start-up time and the alerter was down with it."""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import master_controller as mc  # noqa: E402

IST = mc.IST


def at(y, mo, d, h, mi):
    return IST.localize(datetime(y, mo, d, h, mi))


def test_heartbeat_roundtrip_and_bad_files(tmp_path):
    p = tmp_path / "hb.json"
    assert mc.read_heartbeat(p) is None                       # first ever start: no report
    t = at(2026, 10, 16, 7, 51)
    mc.write_heartbeat(p, t)
    assert mc.read_heartbeat(p) == t
    p.write_text("{garbage")
    assert mc.read_heartbeat(p) is None


def test_the_16_to_19_october_outage_is_counted_exactly():
    eod = CronTrigger(day_of_week="mon-fri", hour=18, minute=30, timezone=IST)
    backup = CronTrigger(hour=2, minute=15, timezone=IST)
    down, up = at(2026, 10, 16, 7, 51), at(2026, 10, 19, 9, 53)
    assert mc.fire_times_between(eod, down, up) == 1           # Fri 18:30 only (weekend, Mon not yet)
    assert mc.fire_times_between(backup, down, up) == 3        # Sat, Sun, Mon 02:15


def test_downtime_missed_skips_one_offs_and_the_heartbeat():
    jobs = [
        SimpleNamespace(id="eod_data_pipeline", trigger=CronTrigger(day_of_week="mon-fri", hour=18, minute=30, timezone=IST)),
        SimpleNamespace(id="startup_catchup", trigger=DateTrigger(run_date=at(2026, 10, 19, 9, 55))),
        SimpleNamespace(id="controller_heartbeat", trigger=CronTrigger(minute="*", timezone=IST)),
        SimpleNamespace(id="never_due", trigger=CronTrigger(month=1, day=1, timezone=IST)),
    ]
    assert mc.downtime_missed(jobs, at(2026, 10, 16, 7, 51), at(2026, 10, 19, 9, 53)) == {"eod_data_pipeline": 1}


def test_catchup_plan_respects_market_hours_and_windows():
    eod = {"eod_data_pipeline": 1}
    # today's case: Monday 09:53, market open → NSE files only; Yahoo + ML wait for 18:30
    mode, when = mc.plan_catchup(at(2026, 10, 19, 9, 53), eod)
    assert mode == "nse" and when == at(2026, 10, 19, 9, 54) + timedelta(seconds=30)
    # inside the ICICI-login / pre-open window → moved to 09:21
    mode, when = mc.plan_catchup(at(2026, 10, 19, 8, 0), eod)
    assert (mode, when.strftime("%H:%M")) == ("nse", "09:21")
    # inside the EOD window → the scheduled jobs do it
    assert mc.plan_catchup(at(2026, 10, 19, 19, 0), eod)[0] == "skip"
    # evening after the window, or early morning, or a weekend: market shut → full pipeline
    assert mc.plan_catchup(at(2026, 10, 19, 22, 0), eod)[0] == "full"
    assert mc.plan_catchup(at(2026, 10, 19, 6, 0), eod)[0] == "full"
    assert mc.plan_catchup(at(2026, 10, 17, 11, 0), eod)[0] == "full"   # Saturday
    # nothing big missed → NSE files only
    assert mc.plan_catchup(at(2026, 10, 19, 22, 0), {})[0] == "nse"
