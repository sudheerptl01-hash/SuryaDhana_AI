"""LWSC honesty (5 Nov review M24, m088): a liquidity-ranked universe instead of the first N tickers alphabetically, a
dated scan that says STALE, ACTIVE flags withheld past their horizon, Benjamini–Hochberg q-values beside the per-stock
p-values, and a freeze-window guard on the heavy scan. Every rule has a negative control. Temp files only."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
from fastapi import BackgroundTasks, HTTPException

import routers.lw_scanner as lw


def _panel() -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2026-08-01", periods=80)
    # AAA..: alphabetically first but illiquid; ZZZ: alphabetically last and the most liquid
    for t, vol in (("AAA", 10), ("AAB", 20), ("MMM", 5_000), ("ZZZ", 90_000), ("ZZY", 60_000)):
        for d in dates:
            rows.append({"ticker": t, "date": d, "close": 100.0, "volume": vol})
    return pd.DataFrame(rows)


def test_universe_is_ranked_by_liquidity_not_alphabet():
    df = _panel()
    assert lw.rank_by_liquidity(df, 3) == ["ZZZ", "ZZY", "MMM"]
    # negative control: the old cut took the alphabetical head
    assert list(df["ticker"].unique())[:3] == ["AAA", "AAB", "MMM"] != lw.rank_by_liquidity(df, 3)
    assert lw.rank_by_liquidity(df.iloc[0:0], 3) == [] and lw.rank_by_liquidity(df, 0) == []


def test_bh_qvalues():
    q = lw.bh_qvalues([0.01, 0.04, 0.03, 0.50, float("nan")])
    assert q[0] == pytest.approx(0.04) and q[2] == pytest.approx(0.05333, abs=1e-4) and q[1] == pytest.approx(0.05333, abs=1e-4)
    assert q[3] == pytest.approx(0.5) and np.isnan(q[4])
    # negative control: 200 tests of pure noise give ~10 raw p < 0.05 and (almost) none after the correction
    rng = np.random.default_rng(1)
    p = rng.uniform(size=200).tolist()
    assert sum(x < 0.05 for x in p) >= 5
    assert sum(x < 0.05 for x in lw.bh_qvalues(p)) <= 1


def test_sessions_and_last_close():
    assert lw.last_close_session(datetime(2026, 11, 6, 9, 0, tzinfo=lw.IST)) == date(2026, 11, 5)     # before the close
    assert lw.last_close_session(datetime(2026, 11, 6, 16, 0, tzinfo=lw.IST)) == date(2026, 11, 6)
    assert lw.last_close_session(datetime(2026, 11, 8, 12, 0, tzinfo=lw.IST)) == date(2026, 11, 6)    # Sunday
    assert lw.sessions_between(date(2026, 10, 14), date(2026, 11, 5)) == 16
    assert lw.sessions_between(date(2026, 11, 5), date(2026, 11, 5)) == 0
    # a file written at 03:52 on 15 Oct holds data to 14 Oct
    assert lw.scan_as_of(None, datetime(2026, 10, 15, 3, 52, tzinfo=lw.IST)) == (date(2026, 10, 14), "file time")
    assert lw.scan_as_of({"as_of": "2026-11-05"}, datetime(2026, 11, 6, 2, 0, tzinfo=lw.IST)) == (date(2026, 11, 5), "scan")


def _write_scan(tmp_path, monkeypatch, mtime: datetime, meta: dict | None = None):
    csv = tmp_path / "scan.csv"
    rows = [{"ticker": f"T{i}", "composite_score": 1 - i / 100, "cycle_edge": 0.1, "cycle_pvalue": 0.01 if i < 3 else 0.6,
             "divergence_count": 1, "divergence_intensity": 0.1, "recent_divergence": False, "failed_breakouts": 1,
             "failure_rate": 0.1, "blast_off_signals": 1, "momentum_strength": 0.5, "is_active_momentum": i == 0,
             "momentum_direction": 1.0} for i in range(40)]
    pd.DataFrame(rows).to_csv(csv, index=False)
    os.utime(csv, (mtime.timestamp(), mtime.timestamp()))
    monkeypatch.setattr(lw, "SCAN_CSV", csv)
    monkeypatch.setattr(lw, "SCAN_META", tmp_path / "meta.json")
    if meta:
        (tmp_path / "meta.json").write_text(json.dumps(meta))


def test_old_scan_is_stale_and_its_active_flags_are_withheld(tmp_path, monkeypatch):
    _write_scan(tmp_path, monkeypatch, datetime(2026, 10, 15, 3, 52, tzinfo=lw.IST))
    out = lw.scan_results_payload(50, now=datetime(2026, 11, 6, 8, 30, tzinfo=lw.IST))
    assert out["as_of"] == "2026-10-14" and out["sessions_behind"] == 16 and out["stale"] is True
    assert out["active_flags_expired"] is True
    top = out["results"][0]
    assert top["active_at_scan"] is True and top["is_active_momentum"] is False
    assert "alphabetical" in out["universe"]                                   # an old scan says how it was cut
    mt = out["multiple_testing"]
    assert mt["n_tests"] == 40 and mt["raw_p_below_05"] == 3 and mt["expected_false_positives_at_p05"] == 2.0
    assert out["badge"] == "heuristic" and out["verdict"]["verdict"] == "FAIL"


def test_fresh_scan_keeps_its_flags(tmp_path, monkeypatch):
    _write_scan(tmp_path, monkeypatch, datetime(2026, 11, 5, 21, 30, tzinfo=lw.IST),
                meta={"as_of": "2026-11-05", "universe": "the 200 most liquid NSE equities"})
    out = lw.scan_results_payload(50, now=datetime(2026, 11, 6, 8, 30, tzinfo=lw.IST))
    # negative control for the rule above: a scan of the last close is neither stale nor stripped of its flags
    assert out["sessions_behind"] == 0 and out["stale"] is False and out["active_flags_expired"] is False
    assert out["results"][0]["is_active_momentum"] is True and out["as_of_source"] == "scan"
    assert out["results"][0]["cycle_qvalue"] is not None


def test_freeze_window_guard(monkeypatch):
    assert lw.in_freeze_window(datetime(2026, 11, 6, 8, 30, tzinfo=lw.IST))
    assert lw.in_freeze_window(datetime(2026, 11, 6, 19, 0, tzinfo=lw.IST))
    assert not lw.in_freeze_window(datetime(2026, 11, 6, 11, 0, tzinfo=lw.IST))     # negative control

    class _Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 6, 8, 30, tzinfo=lw.IST)

    monkeypatch.setattr(lw, "datetime", _Now)
    monkeypatch.setattr(lw, "_jobs", {})
    with pytest.raises(HTTPException) as e:
        asyncio.run(lw.trigger_cycle_scan(BackgroundTasks(), n_stocks=200, confirm=False))
    assert e.value.status_code == 409
    calls: list = []
    bt = BackgroundTasks()
    monkeypatch.setattr(bt, "add_task", lambda *a, **k: calls.append(a))
    out = asyncio.run(lw.trigger_cycle_scan(bt, n_stocks=200, confirm=True))       # an explicit confirm runs it
    assert out["status"] == "queued" and calls
