"""K5 / completeness-final-02 (round 3): while SuryaDhana.app posts the notification feed as native banners (its
notify-sink.alive heartbeat is fresh), the scheduler skips its own osascript banner, which would be a duplicate
shown as 'Script Editor'; osascript stays the fallback when the app is closed or the feed is not served."""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import master_controller as mc  # noqa: E402


def _wire(monkeypatch, tmp_path):
    sink = tmp_path / "notify-sink.alive"
    monkeypatch.setattr(mc, "_APP_SINK", sink)
    monkeypatch.setattr(mc.sys, "platform", "darwin")
    recorded, ran = [], []
    monkeypatch.setattr(mc, "_record_notification", lambda kind, title, body: recorded.append((kind, title)))
    monkeypatch.setattr(mc.subprocess, "run", lambda cmd, **kw: ran.append(cmd[0]))
    return sink, recorded, ran


def test_osascript_runs_when_the_app_is_not_the_sink(monkeypatch, tmp_path):
    sink, recorded, ran = _wire(monkeypatch, tmp_path)
    mc._notify_mac("ALERT RELIANCE", "rose above 1,500", kind="price")      # no heartbeat file at all
    assert ran == ["/usr/bin/osascript"] and recorded == [("price", "ALERT RELIANCE")]
    sink.write_text("{}")
    old = time.time() - 600
    os.utime(sink, (old, old))                                             # the app stopped 10 min ago
    mc._notify_mac("ALERT TCS", "fell below 3,000", kind="price")
    assert ran == ["/usr/bin/osascript"] * 2


def test_a_fresh_heartbeat_skips_the_duplicate_banner_but_still_records_it(monkeypatch, tmp_path):
    sink, recorded, ran = _wire(monkeypatch, tmp_path)
    sink.write_text('{"pid": 1}')
    mc._notify_mac("ALERT INFY", "rose above 1,900", kind="price")
    assert ran == [], "the app shows it from the feed"
    assert recorded == [("price", "ALERT INFY")], "the feed (and the in-page inbox) still get the record"


def test_the_default_sink_path_is_the_apps_config_dir():
    if "SURYADHANA_NOTIFY_SINK" in os.environ:
        return
    assert mc._APP_SINK == Path.home() / "Library/Application Support/ai.suryadhana.terminal/notify-sink.alive"
