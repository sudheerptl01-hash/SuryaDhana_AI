"""P6 — the 19:45 news-scanner track record crashed every evening from 15 Oct 2026 and only logged it.

Root cause: load_prices() returned the evening snapshot's DuckDB *connection* (the Bloomberg F2.3 ops hook) where the
rest of the script expects the price panel, so resolve() died on `panel["close"]` (TypeError: the connection is not
subscriptable) whenever the snapshot was fresh, i.e. every scheduled run.

Everything here runs on a temp DuckDB fixture (never data/market.duckdb, never the real snapshot or pointer), temp
scan files and temp output dirs; Yahoo lookups are replaced by fakes that fail the test if called, and the
controller's alerts are recorded, never sent.
"""
# ruff: noqa: DTZ001 - fixture dates are naive calendar dates, like the scanner's files
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import master_controller as mc
import news_scan_performance as nsp

SESSIONS = pd.bdate_range(end="2026-10-23", periods=90)
EQ_SYMBOLS = [f"S{i:02d}" for i in range(12)] + ["AAA", "BBB"]


def make_market_db(path: Path) -> Path:
    """A small nse_bhavcopy (+ splits) with the columns shared.nse_panel.load_panel reads: 14 EQ names and one SME
    (series SM) name over 90 sessions, smooth prices (no gap the split heuristic would act on)."""
    rng = np.random.default_rng(7)
    rows = []
    for j, sym in enumerate(EQ_SYMBOLS + ["SMEX"]):
        price = 100.0 + 10 * j
        for d in SESSIONS:
            price *= 1 + rng.normal(0.0005, 0.01)
            o = price * (1 + rng.normal(0, 0.002))
            rows.append({"date": d.date(), "symbol": sym, "series": "SM" if sym == "SMEX" else "EQ",
                         "open": o, "high": max(o, price) * 1.01, "low": min(o, price) * 0.99, "close": price,
                         "prev_close": price, "avg_price": price, "volume": 10_000.0 * (j + 1),
                         "deliv_pct": 40.0, "turnover_lacs": 50.0 * (j + 1)})
    cols = list(rows[0])
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE nse_bhavcopy (date DATE, symbol VARCHAR, series VARCHAR, open DOUBLE, high DOUBLE, "
                    "low DOUBLE, close DOUBLE, prev_close DOUBLE, avg_price DOUBLE, volume DOUBLE, deliv_pct DOUBLE, "
                    "turnover_lacs DOUBLE)")
        con.executemany(f"INSERT INTO nse_bhavcopy ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [tuple(r[c] for c in cols) for r in rows])
        con.execute("CREATE TABLE splits (ticker VARCHAR, date TIMESTAMP, ratio DOUBLE)")
    finally:
        con.close()
    return path


def write_scans(scan_dir: Path) -> None:
    scan_dir.mkdir(parents=True, exist_ok=True)
    picks = [
        {"ticker": "AAA.NS", "company_name": "Aaa Industries Limited", "exchange": "NSE", "catalyst_category": "Order win",
         "news_date": "2026-09-28", "conviction_score": "7", "scan_date": "2026-09-29"},
        {"ticker": "BBB.NS", "company_name": "Bbb Limited", "exchange": "NSE", "catalyst_category": "Capacity expansion",
         "news_date": "2026-09-30", "conviction_score": "5", "scan_date": "2026-10-01"},
        {"ticker": "SMEX.NS", "company_name": "Smex Limited", "exchange": "NSE", "catalyst_category": "Tender L1",
         "news_date": "2026-10-05", "conviction_score": "4", "scan_date": "2026-10-06"},
    ]
    (scan_dir / "20261001.json").write_text(json.dumps({"picks": picks[:2]}))
    (scan_dir / "20261006.json").write_text(json.dumps({"picks": picks[2:]}))


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """Temp snapshot DB + temp 'live' DB + temp pointer; the module never sees a real data/ path."""
    snap = make_market_db(tmp_path / "evening-20261023-1920.duckdb")
    (tmp_path / "live").mkdir()
    live = make_market_db(tmp_path / "live" / "market.duckdb")
    monkeypatch.setattr(nsp, "LIVE_DB", live)
    monkeypatch.setattr(nsp, "SNAPSHOT_POINTER", tmp_path / "absent_pointer.json")
    monkeypatch.setattr(nsp, "SCAN_DIR", tmp_path / "scans")
    monkeypatch.setattr(nsp, "nse_names", dict)

    def no_network(*_a, **_k):
        raise AssertionError("the fixture resolves every pick from the panel: no Yahoo call expected")
    monkeypatch.setattr(nsp, "yahoo_daily", no_network)
    monkeypatch.setattr(nsp, "yahoo_search", no_network)
    monkeypatch.setenv("SURYA_SNAPSHOT_PATH", str(snap))
    write_scans(tmp_path / "scans")
    return {"snap": snap, "live": live, "tmp": tmp_path}


# ── root cause ───────────────────────────────────────────────────────────────────────────────────────────────

def test_root_cause_a_connection_is_not_a_panel(world):
    """Negative control for the shape of the bug: what the old load_prices() returned crashes resolve() exactly
    like the nightly runs did."""
    picks = nsp.load_picks()
    con = duckdb.connect(str(world["snap"]), read_only=True)
    try:
        with pytest.raises(TypeError, match="not subscriptable"):
            nsp.resolve(picks, con)
    finally:
        con.close()


class _ConnSpy:
    """Wraps a DuckDB connection and records close(); the test keeps a reference, so reference counting cannot close
    the connection behind load_prices' back (F4-OPS review: the reopen check alone passed without the close())."""

    def __init__(self, con, read_only: bool) -> None:
        self.con, self.read_only, self.closed = con, read_only, False

    def __getattr__(self, name):
        return getattr(self.con, name)

    def close(self) -> None:
        self.closed = True
        self.con.close()


def test_fresh_snapshot_loads_the_panel_read_only_and_closes_it(world, monkeypatch):
    real_connect = duckdb.connect
    opened: list[_ConnSpy] = []

    def spy_connect(*a, **k):
        opened.append(_ConnSpy(real_connect(*a, **k), bool(k.get("read_only"))))
        return opened[-1]
    monkeypatch.setattr(nsp.duckdb, "connect", spy_connect)
    panel = nsp.load_prices("2026-05-01")
    monkeypatch.setattr(nsp.duckdb, "connect", real_connect)
    assert isinstance(panel, dict), "load_prices must return the panel, never the DuckDB connection"
    assert {"AAA", "BBB"} <= set(panel["close"].columns) and "SMEX" not in panel["close"].columns
    assert panel["close"].index.max() == pd.Timestamp("2026-10-23")
    assert "SMEX" in panel["other"]["close"].columns                       # SME series come along
    assert panel["other"]["close"].index.equals(panel["close"].index)
    assert len(opened) == 1 and opened[0].read_only, "one read-only open of the snapshot, no private copy"
    assert opened[0].closed, "load_prices must close the snapshot handle itself"
    # with the handle still referenced here, a read-write open of the same file works only because it was closed
    real_connect(str(world["snap"])).close()


def test_snapshot_is_used_instead_of_the_live_db(world, monkeypatch):
    copies = []
    monkeypatch.setattr(nsp.shutil, "copy2", lambda *a, **k: copies.append(a))
    nsp.load_prices("2026-05-01")
    assert copies == [], "a fresh snapshot must not trigger a private copy of the live DB"


def test_stale_or_missing_snapshot_falls_back_to_a_private_copy(world, monkeypatch):
    past = time.time() - 30 * 3600
    os.utime(world["snap"], (past, past))                               # older than 24 h
    assert nsp.snapshot_path() is None
    tmpdirs = []
    real_mkdtemp = nsp.tempfile.mkdtemp
    monkeypatch.setattr(nsp.tempfile, "mkdtemp",
                        lambda **k: tmpdirs.append(real_mkdtemp(dir=world["tmp"], **k)) or tmpdirs[-1])
    panel = nsp.load_prices("2026-05-01")
    assert "AAA" in panel["close"].columns
    assert tmpdirs and not Path(tmpdirs[0]).exists(), "the private copy is removed afterwards"
    monkeypatch.setenv("SURYA_SNAPSHOT_PATH", str(world["tmp"] / "gone.duckdb"))
    assert nsp.snapshot_path() is None


def test_unreadable_snapshot_falls_back_to_a_private_copy(world, capsys):
    world["snap"].write_bytes(b"not a duckdb file" * 64)
    panel = nsp.load_prices("2026-05-01")
    assert "BBB" in panel["close"].columns
    assert "using a private copy" in capsys.readouterr().err


def test_pointer_file_is_honoured_without_the_env_var(world, monkeypatch, tmp_path):
    monkeypatch.delenv("SURYA_SNAPSHOT_PATH")
    pointer = tmp_path / "pointer.json"
    pointer.write_text(json.dumps({"path": str(world["snap"])}))
    monkeypatch.setattr(nsp, "SNAPSHOT_POINTER", pointer)
    assert nsp.snapshot_path() == world["snap"]
    pointer.write_text("{garbage")
    assert nsp.snapshot_path() is None


def test_main_end_to_end_on_the_fixture(world):
    out = world["tmp"] / "out"
    nsp.main(["--out", str(out)])
    tr = json.loads((out / "track_record.json").read_text())
    assert tr["prices_through"] == "2026-10-23" and tr["picks"] == 3 and tr["scans"] == 3   # distinct scan dates
    rows = {r["symbol"]: r for r in tr["rows"]}
    assert rows["AAA"]["nse_symbol"] == "AAA" and rows["SMEX"]["nse_symbol"] == "other:SMEX"
    assert all(r["status"] == "open" and r["r_to_date_pct"] is not None for r in rows.values())
    assert (out / "REPORT.md").read_text().startswith("# News scanner track record")
    assert (out / "picks.csv").exists()


# ── the controller job: a failure now raises the WARNING alert path and shows as `error` ─────────────────────

class _Alerts:
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    async def info(self, title, body):
        self.sent.append(("info", title, body))

    async def warning(self, title, body):
        self.sent.append(("warning", title, body))

    async def critical(self, title, body):
        self.sent.append(("critical", title, body))


@pytest.fixture()
def controller(monkeypatch):
    alerts = _Alerts()
    monkeypatch.setattr(mc, "_alerts", alerts)
    monkeypatch.setattr(mc, "_latency", mc.LatencyTracker())
    monkeypatch.setattr(mc, "_history", mc.JobHistory(Path("/nonexistent/never-written.json")))   # not armed
    monkeypatch.setattr(mc, "_evening_snapshot_env", dict)
    calls: list[list[str]] = []

    def run_with(rc: int, stderr: str = "", exc: Exception | None = None):
        def fake_run(cmd, **kw):
            calls.append(cmd)
            if exc is not None:
                raise exc
            return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=stderr)
        monkeypatch.setattr(mc.subprocess, "run", fake_run)
    return {"alerts": alerts, "calls": calls, "run_with": run_with}


CRASH = ("Traceback (most recent call last):\n  File \"scripts/news_scan_performance.py\", line 344, in main\n"
         "    res = measure(resolve(picks, panel), panel)\n"
         "TypeError: '_duckdb.DuckDBPyConnection' object is not subscriptable\n")


def test_failed_run_sends_a_warning_with_the_reason_and_marks_error(controller):
    controller["run_with"](1, CRASH)
    asyncio.run(mc.news_track_record_daily())
    assert controller["calls"] and controller["calls"][0][-1].endswith("news_scan_performance.py")
    [(level, title, body)] = controller["alerts"].sent
    assert (level, title) == ("warning", "News track record failed")
    assert "exit 1" in body and "not subscriptable" in body
    st = mc._latency.stats()["news_track_record_daily"]
    assert st["last_status"] == "error"
    assert mc._history.get("news_track_record_daily")["last_status"] == "error"


def test_clean_run_sends_nothing_and_is_done(controller):
    controller["run_with"](0)
    asyncio.run(mc.news_track_record_daily())
    assert controller["alerts"].sent == []
    assert mc._latency.stats()["news_track_record_daily"]["last_status"] == "done"


def test_timeout_also_warns(controller):
    controller["run_with"](0, exc=subprocess.TimeoutExpired(cmd="x", timeout=1800))
    asyncio.run(mc.news_track_record_daily())
    [(level, _title, body)] = controller["alerts"].sent
    assert level == "warning" and "TimeoutExpired" in body
    assert mc._latency.stats()["news_track_record_daily"]["last_status"] == "error"


def test_stderr_reason_picks_the_exception_line():
    assert mc._stderr_reason(CRASH).startswith("TypeError:")
    assert mc._stderr_reason("") == "no stderr" and mc._stderr_reason(None) == "no stderr"


def test_fixture_dates_cover_the_scans():
    """Guard for the fixture itself: the scans sit well inside the 90 sessions (entry, horizons measurable)."""
    assert SESSIONS[0] < pd.Timestamp(datetime(2026, 7, 1)) < pd.Timestamp("2026-10-06") < SESSIONS[-1]
