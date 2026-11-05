"""GOLD wave 1d (5 Nov 2026): the stale MCX settlement baseline and the review's API-side items — every rule with a negative
control. Offline: the recorded Breeze 1-minute bars of 03/04 Nov (fixtures/mcx_gold_dec26_1m_close_20261103_04.json, prices
and volumes only), test_gold's data-service fake and pinned clock, no broker, no Yahoo, no data-service.

The blocker, as the PM measured it: the ICICI band midpoint the page called "Wed 04 Nov settlement" (₹1,39,452) is TUESDAY's
last-30-min VWAP (₹1,39,448); Wednesday's is ₹1,43,237. The settlement is now the latest completed session's last-30-min VWAP
(Breeze, one call per contract per session), else the band labelled with the session it really belongs to; `settlement_check`
compares the two and the accuracy log's stale flag uses the same 0.6 % test.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import routers.gold_preopen as gp  # noqa: E402
from routers import gold, mcx  # noqa: E402
from test_gold import NOW, _app, _offline  # noqa: E402,F401 — the autouse fakes (no network) and the app

IST = gp.IST
FIX = Path(__file__).resolve().parent / "fixtures" / "mcx_gold_dec26_1m_close_20261103_04.json"
DEC26 = date(2026, 12, 4)
TUE, WED, THU = date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)
BAND_05NOV = 139_452.0  # the 05 Nov ICICI file's GOLD DEC-26 band midpoint (135,269 – 143,635)


@pytest.fixture
def client() -> Any:
    with TestClient(_app()) as c:
        yield c


def _bars(day: date) -> list[dict[str, Any]]:
    return json.loads(FIX.read_text(encoding="utf-8"))["sessions"][day.isoformat()]


def _flat_bars(session: date, price: float, upto_min: int = 30) -> list[dict[str, Any]]:
    """30 one-minute bars at `price` in `session`'s settlement window (23:00–23:30 in US daylight time, else 23:25–23:55),
    the last `30 − upto_min` minutes missing."""
    close = gp.session_close_at(session)
    return [{"datetime": (close - timedelta(minutes=30 - k)).strftime("%Y-%m-%d %H:%M:%S"), "close": price, "volume": 5}
            for k in range(upto_min)]


def _ok(value: float, session: date, expiry: date = DEC26, last_close: float | None = None) -> dict[str, Any]:
    return {"status": "ok", "value": value, "bars": 30, "volume": 160.0, "method": "volume-weighted", "window": "23:25–23:55 IST",
            "last_close": last_close or value, "session": session.isoformat(), "source": "breeze_vwap30",
            "stock_code": "GOLD", "expiry": expiry.isoformat()}


# ── 1. the last-30-min VWAP on the recorded bars ────────────────────────────────────────────────────────────────────


def test_vwap30_of_the_recorded_bars_is_the_pm_measurement() -> None:
    wed = gp.vwap_last_minutes(_bars(WED), gp.session_close_at(WED))
    tue = gp.vwap_last_minutes(_bars(TUE), gp.session_close_at(TUE))
    assert wed is not None and tue is not None
    assert wed["value"] == pytest.approx(143_236.8, abs=0.1) and round(wed["value"]) == 143_237   # PM: ₹1,43,237
    assert tue["value"] == pytest.approx(139_448.0, abs=0.1)                                      # PM: ₹1,39,448
    assert wed["bars"] == 30 and wed["window"] == "23:25–23:55 IST" and wed["method"] == "volume-weighted"
    assert wed["last_close"] == 143_293.0                                                         # PM: last close ₹1,43,293
    # negative controls: the 23:24 bar (outside the window) and a bar at/after the close never count
    bogus = [*_bars(WED), {"datetime": "2026-11-04 23:55:00", "close": 1.0e6, "volume": 1.0e6},
             {"datetime": "2026-11-04 23:10:00", "close": 1.0, "volume": 1.0e6}]
    assert gp.vwap_last_minutes(bogus, gp.session_close_at(WED))["value"] == wed["value"]
    assert gp.vwap_last_minutes([], gp.session_close_at(WED)) is None
    flat = [{**b, "volume": 0} for b in _bars(WED)]
    eq = gp.vwap_last_minutes(flat, gp.session_close_at(WED))
    assert eq["method"].startswith("equal-weight") and eq["value"] != wed["value"]


def test_the_band_of_a_file_is_the_settlement_two_sessions_back() -> None:
    assert gp.band_session(THU) == TUE and gp.band_applies_to(THU) == WED         # the 05 Nov file: Tue's settle, Wed's band
    assert gp.band_session(WED) == date(2026, 11, 2)                              # the 04 Nov file: Mon 02 Nov (1,40,186 ≈ 1,40,190)
    assert gp.band_session(date(2026, 10, 28)) == date(2026, 10, 26)              # 1,43,073 ≈ Mon 26 Oct 1,43,069
    assert gp.band_session(date(2026, 11, 2)) == date(2026, 10, 29)               # Monday's file skips the weekend
    # negative control: never the session right before the file (the label the page used to print)
    assert gp.band_session(THU) != gp.previous_session(THU)


def test_latest_completed_session_waits_for_the_close_and_the_last_bar() -> None:
    at = lambda d, h, m: datetime(d.year, d.month, d.day, h, m, tzinfo=IST)  # noqa: E731
    assert gp.latest_completed_session(at(THU, 22, 20)) == WED                    # tonight, mid-session
    assert gp.latest_completed_session(at(THU, 23, 56)) == WED                    # 23:55 close + 2 min grace not reached
    assert gp.latest_completed_session(at(THU, 23, 58)) == THU
    assert gp.latest_completed_session(at(date(2026, 11, 7), 12, 0)) == date(2026, 11, 6)   # Saturday → Friday
    assert gp.latest_completed_session(at(date(2026, 11, 9), 8, 45)) == date(2026, 11, 6)   # Monday pre-open → Friday
    assert gp.session_close_at(date(2026, 10, 27)).strftime("%H:%M") == "23:30"   # US daylight time
    assert gp.session_close_at(WED).strftime("%H:%M") == "23:55"


# ── 2. the settlement block and its check ─────────────────────────────────────────────────────────────────────────


def test_settlement_check_flags_the_pm_evidence_and_not_a_matching_band() -> None:
    wed = gp.vwap_last_minutes(_bars(WED), gp.session_close_at(WED))["value"]
    tue = gp.vwap_last_minutes(_bars(TUE), gp.session_close_at(TUE))["value"]
    stale = gp.settlement_check(BAND_05NOV, wed, TUE, WED)
    assert stale["flagged"] is True and stale["band_vs_vwap30_pct"] == pytest.approx(-2.64, abs=0.01)
    assert "Tue 03 Nov" in stale["compared"] and "Wed 04 Nov" in stale["compared"]
    same = gp.settlement_check(BAND_05NOV, tue, TUE, TUE)                       # the band IS Tuesday's settlement
    assert same["flagged"] is False and abs(same["band_vs_vwap30_pct"]) < 0.01
    assert gp.settlement_check(100.6, 100.0)["flagged"] is False                 # exactly 0.6 % is inside
    assert gp.settlement_check(100.61, 100.0)["flagged"] is True
    none = gp.settlement_check(BAND_05NOV, None)
    assert none["flagged"] is False and none["band_vs_vwap30_pct"] is None and "no last-30-min VWAP" in none["note"]


def test_settlement_block_uses_the_vwap_else_the_band_of_its_real_session() -> None:
    vw = {"status": "ok", **gp.vwap_last_minutes(_bars(WED), gp.session_close_at(WED))}
    a = gp.settlement_block(BAND_05NOV, THU, vw, WED)
    assert a["settlement"] == pytest.approx(143_236.8, abs=0.1) and a["settlement_source"] == "breeze_vwap30"
    assert a["settlement_session"] == "2026-11-04" and a["settlement_session_label"] == "Wed 04 Nov settlement"
    assert a["settlement_quality"] == "vwap30_proxy" and "proxy" in a["settlement_method"]
    assert a["band_midpoint"] == BAND_05NOV and a["band_session"] == "2026-11-03"
    assert a["band_session_label"] == "Tue 03 Nov settlement" and a["band_applies_to"] == "2026-11-04"
    assert a["settlement_check"]["flagged"] is True and a["settlement_is_latest"] and a["settlement_note"] is None
    # no Breeze session: the band, LABELLED with Tuesday (never 'Wed 04 Nov settlement'), and the note says what is missing
    b = gp.settlement_block(BAND_05NOV, THU, {"status": "no_session"}, WED)
    assert b["settlement"] == BAND_05NOV and b["settlement_source"] == "band_midpoint" and b["settlement_quality"] == "band_proxy"
    assert b["settlement_session_label"] == "Tue 03 Nov settlement" and b["settlement_is_latest"] is False
    assert "Wed 04 Nov" in b["settlement_note"] and "no session" in b["settlement_note"]
    assert b["settlement_check"]["flagged"] is False and b["settlement_check"]["band_vs_vwap30_pct"] is None
    # a failed VWAP status is never used as a price
    c = gp.settlement_block(BAND_05NOV, THU, {"status": "empty", "value": 1.0}, WED)
    assert c["settlement_source"] == "band_midpoint"


def test_the_fair_open_on_the_vwap_baseline_misses_by_about_a_hundred_not_3724() -> None:
    """The 05 Nov 08:45 snapshot's own inputs (COMEX GCZ26 ref 4,077.22 → 4,139.4, USD/INR 94.63 → 94.53) and the actual
    open ₹1,45,153: on the band baseline the model missed by +₹3,724 (logged); on Wednesday's VWAP it misses by ≈ −₹100."""
    vwap = gp.vwap_last_minutes(_bars(WED), gp.session_close_at(WED))["value"]
    on_vwap = gp.fair_open(vwap, 4077.22, 4139.4, 94.63, 94.53, 15.0, fineness=995)["fair_open"]
    on_band = gp.fair_open(BAND_05NOV, 4077.22, 4139.4, 94.63, 94.53, 15.0, fineness=995)["fair_open"]
    assert abs(145_153 - on_vwap) < 300                                          # inside the ₹300 house limit
    assert 145_153 - on_band == pytest.approx(3_724, abs=5)                       # negative control: the logged miss


# ── 3. one Breeze call per contract per session, through the ledger ─────────────────────────────────────────────────


def test_one_breeze_call_per_contract_per_session_and_misses_are_short_lived(monkeypatch: pytest.MonkeyPatch) -> None:
    gp._settle_cache.clear()
    calls: list[tuple[str, date, date]] = []

    def fake(stock: str, expiry: date, session: date) -> tuple[list[dict[str, Any]] | None, str]:
        calls.append((stock, expiry, session))
        time.sleep(0.05)
        return _bars(session), "ok"

    monkeypatch.setattr(gp, "_breeze_session_bars", fake)
    out: list[dict[str, Any]] = []
    threads = [threading.Thread(target=lambda: out.append(gp.session_vwap("GOLD", DEC26, WED))) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1 and all(o["value"] == out[0]["value"] for o in out)   # single flight
    gp.session_vwap("GOLD", DEC26, WED)
    gp.session_vwap("GOLD", DEC26, TUE)                                          # another session = another call
    gp.session_vwap("GOLDTE", date(2026, 11, 30), WED)                           # another contract = another call
    assert len(calls) == 3
    assert asyncio.run(gp.session_vwap_async("GOLD", DEC26, WED))["status"] == "ok" and len(calls) == 3
    # a miss is cached briefly (no retry storm) and carries its reason
    gp._settle_cache.clear()
    monkeypatch.setattr(gp, "_breeze_session_bars", lambda s, e, d: (None, "no_session"))
    assert gp.session_vwap("GOLD", DEC26, WED)["status"] == "no_session"
    gp._settle_cache.clear()


def test_the_breeze_read_goes_through_the_budget_ledger_and_stops_at_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    import routers.positions as pos
    from shared import breeze_budget as bb

    class FakeBreeze:
        calls = 0

        def get_historical_data_v2(self, **kw: Any) -> dict[str, Any]:
            FakeBreeze.calls += 1
            assert kw["interval"] == "1minute" and kw["exchange_code"] == "MCX" and kw["stock_code"] == "GOLD"
            assert kw["from_date"] == "2026-11-04T23:15:00.000Z" and kw["to_date"] == "2026-11-04T23:59:00.000Z"
            return {"Status": 200, "Success": _bars(WED)}

    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (FakeBreeze(), None))
    # under pytest the read is OFF unless asked for (a test never reaches the live broker)
    assert gp.settle_breeze_enabled() is False and gp._breeze_session_bars("GOLD", DEC26, WED) == (None, "disabled")
    monkeypatch.setenv("GOLD_SETTLE_BREEZE", "1")
    bb.reset_ledger()
    before = bb.ledger().status()
    bars, status = gp._breeze_session_bars("GOLD", DEC26, WED)
    assert status == "ok" and len(bars) == 31 and FakeBreeze.calls == 1
    after = bb.ledger().status()
    assert json.dumps(after, default=str) != json.dumps(before, default=str)       # the call was recorded

    def refuse(caller: str, method: str = "") -> Any:
        raise bb.BudgetExceeded(bb.Decision(allowed=False, reason="cap_day", caller=caller, method=method, used_minute=0,
                                            used_day=4000, caller_used_day=0, cap_minute=60, cap_day=4000, caller_quota=None))

    monkeypatch.setattr(bb.ledger(), "acquire", refuse)
    assert gp._breeze_session_bars("GOLD", DEC26, WED) == (None, "budget") and FakeBreeze.calls == 1   # the SDK never ran
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (None, "no session"))
    assert gp._breeze_session_bars("GOLD", DEC26, WED) == (None, "no_session")
    bb.reset_ledger()


# ── 4. the accuracy log: the stale flag on the PM's evidence, nothing re-scored ──────────────────────────────────────


LOG_0511 = {"date": "2026-11-05", "baseline": BAND_05NOV, "baseline_session": "2026-11-04", "expiry": "2026-12-04",
            "fair_open": 141_429.0, "actual_open": 145_153.0, "error": 3_724.0, "naive_error": 5_701.0, "stale_baseline": False}


def test_the_log_flags_tuesdays_band_labelled_wednesday_and_keeps_the_numbers() -> None:
    wed = {"status": "ok", **gp.vwap_last_minutes(_bars(WED), gp.session_close_at(WED))}
    chk = gp.baseline_check(LOG_0511, wed)
    assert chk["flagged"] is True and chk["band_vs_vwap30_pct"] == pytest.approx(-2.64, abs=0.01)
    assert "labelled Wed 04 Nov" in chk["compared"]
    assert gp.stale_baseline(LOG_0511, wed) is True
    # negative controls: the right settlement under the same label is not stale; no VWAP known → unknown, never guessed
    good = {**LOG_0511, "baseline": 143_237.0}
    assert gp.stale_baseline(good, wed) is False and gp.baseline_check(good, wed)["flagged"] is False
    assert gp.baseline_check(LOG_0511, None) is None and gp.stale_baseline(LOG_0511, None) is False
    # the recorded check of a wave-1d snapshot row wins; a VWAP baseline is never stale by the check
    assert gp.baseline_check({**LOG_0511, "baseline_source_kind": "breeze_vwap30"})["flagged"] is False


# The REAL row shapes of data/gold_preopen/log.json (prices only; read-only copy, 5 Nov): rows written before 05 Nov carry
# no `expiry` and no `baseline_source_kind` — only the contract label and the old source text (round-2 checker major).
REAL_ROWS: dict[str, dict[str, Any]] = {
    "2026-10-12": {"date": "2026-10-12", "contract": "GOLD DEC-26", "baseline": 149_610.0, "fair_open": 149_971.0,
                   "baseline_source": "MCX settlement 09 Oct (price-band midpoint)", "actual_open": 151_061.0,
                   "error": 1_090.0, "naive_error": 1_451.0},
    "2026-10-20": {"date": "2026-10-20", "contract": "GOLD DEC-26", "baseline": 147_489.0, "fair_open": 146_669.0,
                   "baseline_source": "MCX settlement 16 Oct (price-band midpoint)"},
    "2026-10-26": {"date": "2026-10-26", "contract": "GOLD DEC-26", "baseline": 143_309.0, "fair_open": 143_765.0,
                   "baseline_source": "MCX settlement 23 Oct (price-band midpoint)", "actual_open": 142_301.0,
                   "error": -1_464.0, "naive_error": -1_008.0},
    "2026-10-27": {"date": "2026-10-27", "contract": "GOLD DEC-26", "baseline": 142_024.0, "fair_open": 141_521.0,
                   "baseline_source": "MCX settlement 26 Oct (price-band midpoint)", "actual_open": 142_581.0,
                   "error": 1_060.0, "naive_error": 557.0},
    "2026-10-28": {"date": "2026-10-28", "contract": "GOLD DEC-26", "baseline": 143_073.0, "fair_open": 142_611.0,
                   "baseline_source": "MCX settlement 27 Oct (price-band midpoint)", "actual_open": 143_867.0,
                   "error": 1_256.0, "naive_error": 794.0},
    "2026-10-30": {"date": "2026-10-30", "actual_open": 142_249.0, "actual_source": "ICICI Breeze (1-min bars)"},
    "2026-11-05": {**LOG_0511, "contract": "GOLD DEC-26", "baseline_source": "MCX settlement 04 Nov (price-band midpoint)"},
}
# the last-30-min VWAPs of the sessions those rows were LABELLED with (Breeze, measured 5 Nov by G-API and the critic)
MEASURED = {date(2026, 11, 4): 143_236.8, date(2026, 10, 23): 142_035.6, date(2026, 10, 26): 143_068.8,
            date(2026, 10, 27): 144_140.4}


def test_log_rows_and_stats_name_the_stale_rows_without_rescoring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On the REAL row shape (no `expiry`): the expiry comes from the label (D2), every band row is flagged by the verified
    band rule without a Breeze read, the VWAP check adds its measure, the counterfactual sits beside the recorded numbers."""
    log = tmp_path / "log.json"
    log.write_text(json.dumps(REAL_ROWS), encoding="utf-8")
    monkeypatch.setenv("GOLD_LOG_PATH", str(log))
    gp._settle_cache.clear()
    assert all("expiry" not in r for d, r in REAL_ROWS.items() if d != "2026-11-05")
    assert gp.expiry_from_label("GOLD DEC-26") == ("GOLD", DEC26) and gp.expiry_from_label("GOLDTEN NOV-26")[1] == date(2026, 11, 30)
    assert gp.expiry_from_label("GOLD XYZ-26") is None and gp.expiry_from_label("silver") is None   # negative controls
    assert gp._row_vwap_args(REAL_ROWS["2026-10-26"]) == ("GOLD", DEC26, date(2026, 10, 23))
    assert gp._row_vwap_args(REAL_ROWS["2026-10-30"]) is None                       # no baseline: nothing to check
    # the 20 Oct row used the 19 Oct master (Dussehra morning): its label names Fri 16 Oct, not the snapshot-day rule
    assert gp.labelled_session(REAL_ROWS["2026-10-20"]) == date(2026, 10, 16)
    out = {r["date"]: r for r in gp.log_rows(20)}
    band_days = ["2026-10-12", "2026-10-26", "2026-10-27", "2026-10-28", "2026-11-05"]
    for d in band_days:
        br = out[d]["band_rule"]
        assert out[d]["stale_baseline"] is True and "band_rule" in out[d]["stale_reasons"], d
        assert br["mislabelled"] and br["real_session"] == gp.previous_session(date.fromisoformat(br["labelled_session"])).isoformat()
    assert out["2026-10-26"]["band_rule"]["real_session"] == "2026-10-22"         # Thu 22 Oct VWAP 1,43,307.9 = this band
    assert out["2026-10-30"]["stale_baseline"] is False and out["2026-10-30"]["band_rule"] is None
    s = gp.accuracy_stats(list(out.values()), 300)
    assert s["days"] == 5 and s["stale_baseline_count"] == 5 and s["stale_baseline_dates"] == band_days
    assert s["stale_baseline_unknown"] == [] and s["excluding_stale"] == {"days": 0}   # no clean morning before wave 1d
    assert s["stale_by"]["band_rule"] == band_days and s["on_vwap30"] == {"days": 0}
    # with the measured VWAPs: the check flags each row by its session's move, the counterfactual sits beside the numbers
    for sess, v in MEASURED.items():
        gp._settle_cache.set(gp._settle_key("GOLD", DEC26, sess), _ok(v, sess))
    out = {r["date"]: r for r in gp.log_rows(20)}
    pct = {d: out[d]["baseline_check"]["band_vs_vwap30_pct"] for d in ("2026-10-26", "2026-10-27", "2026-10-28", "2026-11-05")}
    assert pct == {"2026-10-26": 0.9, "2026-10-27": -0.73, "2026-10-28": -0.74, "2026-11-05": -2.64}
    assert all("vwap30_check" in out[d]["stale_reasons"] for d in pct)
    rx = out["2026-11-05"]["re_explained"]
    assert rx["fair_open_on_vwap30"] == 145_267.0 and rx["error_on_vwap30"] == -114.0     # the ≈ −₹115 of round 1
    assert out["2026-11-05"]["error"] == 3_724.0 and out["2026-10-28"]["naive_error"] == 794.0   # nothing re-scored
    s = gp.accuracy_stats(list(out.values()), 300)
    assert s["mean_abs_error"] == pytest.approx((1_090 + 1_464 + 1_060 + 1_256 + 3_724) / 5, abs=0.1)   # recorded, as before
    cf = s["on_vwap30"]
    assert cf["days"] == 4 and cf["dates"] == ["2026-10-26", "2026-10-27", "2026-10-28", "2026-11-05"]
    assert cf["mean_abs_error"] == pytest.approx((187 + 19 + 192 + 114) / 4, abs=1) and cf["naive_mean_abs_error"] > 700
    assert "counterfactual" in cf["note"]
    assert json.loads(log.read_text(encoding="utf-8")) == REAL_ROWS                     # the file untouched
    # negative controls: a wave-1d band row is labelled with its REAL session (no band-rule flag); a typed baseline is no band
    w1d = {"date": "2026-11-06", "contract": "GOLD DEC-26", "expiry": "2026-12-04", "baseline": 139_452.0,
           "baseline_session": "2026-11-03", "baseline_source_kind": "band_midpoint", "settlement_check": {
               "band_vs_vwap30_pct": -2.64, "flagged": True}}
    assert gp.band_rule(w1d)["mislabelled"] is False and "band_rule" not in gp.stale_reasons(w1d)
    assert gp.baseline_check(w1d) is None            # its settlement_check compares another session: not the baseline's check
    typed = {"date": "2026-10-12", "contract": "GOLD DEC-26", "baseline": 149_000.0, "baseline_source": "your entry"}
    assert gp.band_rule(typed) is None and gp.stale_reasons(typed) == []
    gp._settle_cache.clear()


def test_the_0845_snapshot_records_its_settlement_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_gold_preopen import _FrozenDatetime, _Upstream, desk as _desk  # noqa: F401

    monkeypatch.setenv("GOLD_LOG_PATH", str(tmp_path / "log.json"))
    import test_gold_preopen as tgp

    real_client = gp.httpx.AsyncClient
    gp._cache.clear()
    gp._settle_cache.clear()
    monkeypatch.setattr(gp, "_load_mcx_master", lambda: (tgp.HEADER + tgp.ROWS, date(2026, 10, 26)))
    monkeypatch.setattr(gp, "_breeze_mcx_quote", lambda expiry: None)
    monkeypatch.setattr(gp, "_breeze_mcx_open", lambda expiry, day: None)
    monkeypatch.setattr(gp, "_refresh_treasury_in_background", lambda: None)
    monkeypatch.setattr(gp, "datetime", _FrozenDatetime)
    transport = gp.httpx.MockTransport(_Upstream())
    monkeypatch.setattr(gp.httpx, "AsyncClient", lambda *a, **k: real_client(*a, **{**k, "transport": transport}))
    # Mon 26 Oct 08:40: the latest completed session is Fri 23 Oct; its VWAP is known
    gp._settle_cache.set(gp._settle_key("GOLD", DEC26, date(2026, 10, 23)), _ok(152_000.0, date(2026, 10, 23)))
    row = asyncio.run(gp.gold_snapshot(force=False))
    assert row["baseline"] == 152_000.0 and row["baseline_session"] == "2026-10-23" and row["baseline_source_kind"] == "breeze_vwap30"
    assert row["stale_baseline"] is False and row["band_session"] == "2026-10-22" and row["settlement_check"]["flagged"] is True
    assert row["baseline_check"]["flagged"] is False
    # negative control: no VWAP → the band of its REAL session (Thu 22 Oct), flagged stale by the session rule
    gp._cache.clear()
    gp._settle_cache.clear()
    tomorrow = (tmp_path / "log2.json")
    monkeypatch.setenv("GOLD_LOG_PATH", str(tomorrow))
    row2 = asyncio.run(gp.gold_snapshot(force=False))
    assert row2["baseline_source_kind"] == "band_midpoint" and row2["baseline_session"] == "2026-10-22"
    assert row2["stale_baseline"] is True and "(ICICI price-band midpoint, proxy)" in row2["baseline_source"]
    gp._cache.clear()
    gp._settle_cache.clear()


# ── 5. the CONTRACT on /fair, /health, /overview, /contracts, MCXG ─────────────────────────────────────────────────


SETTLE_FIELDS = ("settlement", "settlement_source", "settlement_session", "settlement_session_label", "settlement_quality",
                 "band_midpoint", "band_session", "settlement_check")


def test_the_contract_fields_are_served_everywhere_the_band_used_to_be(client: TestClient) -> None:
    gp._settle_cache.set(gp._settle_key("GOLD", DEC26, date(2026, 10, 23)), _ok(146_900.0, date(2026, 10, 23)))
    h = client.get("/api/gold/health").json()["fair"]
    o = client.get("/api/gold/overview").json()
    s = o["strip"]
    for blk in (h, s):
        for k in SETTLE_FIELDS:
            assert k in blk, k
    assert h["settlement"] == 146_900.0 and h["settlement_source"] == "breeze_vwap30" and h["settlement_quality"] == "vwap30_proxy"
    assert h["settlement_session_label"] == "Fri 23 Oct settlement" and h["band_session_label"] == "Thu 22 Oct settlement"
    assert h["settlement_check"]["band_vs_vwap30_pct"] == pytest.approx((146_080 / 146_900 - 1) * 100, abs=0.01)
    assert s["mcx_settle"] == 146_900.0 and s["mcx_settle_source"] == "breeze_vwap30" and s["basis_session_label"] == "Fri 23 Oct settlement"
    assert "at the" not in s["basis_session_label"]                    # the session only: the strip wraps it once
    # /fair runs the desk on the wall clock (gold_preopen is not pinned here): seed ITS latest session too
    desk_latest = gp.latest_completed_session(datetime.now(IST))
    gp._settle_cache.set(gp._settle_key("GOLD", DEC26, desk_latest), _ok(146_900.0, desk_latest))
    fair = client.get("/api/gold/fair").json()["baseline"]
    assert fair["value"] == 146_900.0 and fair["settlement_source"] == "breeze_vwap30" and fair["session"] == desk_latest.isoformat()
    # 1,46,080 vs 1,46,900 = −0.56 %: inside the 0.6 % limit, so NOT flagged (the check is a test, not a label)
    assert fair["settlement_check"]["band_vs_vwap30_pct"] == -0.56 and fair["settlement_check"]["flagged"] is False
    assert fair["band_session"] == "2026-10-22"
    # negative control: without the VWAP everything falls back to the band of its real session (Thu 22 Oct), labelled so
    gp._settle_cache.clear()
    gold._ttl.clear()
    mcx._cache.clear()
    h2 = client.get("/api/gold/health").json()["fair"]
    assert h2["settlement"] == 146_080.0 and h2["settlement_source"] == "band_midpoint" and h2["settlement_quality"] == "band_proxy"
    assert h2["settlement_session_label"] == "Thu 22 Oct settlement" and h2["settlement_check"]["flagged"] is False


def test_contracts_cards_use_the_vwap_where_read_and_never_carry_across_sessions(client: TestClient) -> None:
    gp._settle_cache.set(gp._settle_key("GOLD", DEC26, date(2026, 10, 23)), _ok(146_900.0, date(2026, 10, 23)))
    body = client.get("/api/gold/contracts").json()
    g = next(f for f in body["families"] if f["code"] == "GOLD")
    dec, feb = g["expiries"][0], g["expiries"][1]
    assert dec["settle"] == 146_900.0 and dec["settle_source"] == "breeze_vwap30" and dec["settle_session"] == "2026-10-23"
    assert feb["settle_source"] == "band_midpoint" and feb["settle_session_label"] == "Thu 22 Oct settlement"
    assert feb["carry_pct"] is None and "different sessions" in feb["carry_note"]   # a day's move is not carry
    assert g["one_pct_move_inr"] == round(146_900.0 * 100 / 100) and "Fri 23 Oct" in g["price_basis"]
    assert body["master"]["session_label"] == "Thu 22 Oct settlement" and body["master"]["band_applies_to"] == "2026-10-23"
    assert "COMEX's own annual carry" in body["carry_fair_note"]
    guinea = next(f for f in body["families"] if f["code"] == "GOLDGUINEA")
    assert guinea["purity"] == "999" and guinea["basis_reference"] == "landed_999"   # PM decision D1: the guinea is 999
    # negative control: with no VWAP read, every expiry is the band of ONE session and carry is printed
    gp._settle_cache.clear()
    g2 = next(f for f in client.get("/api/gold/contracts").json()["families"] if f["code"] == "GOLD")
    assert g2["expiries"][1]["carry_pct"] is not None and g2["expiries"][0]["settle_source"] == "band_midpoint"


# ── 6. India basis: purity-correct, ONE value per clock ─────────────────────────────────────────────────────────────


def test_purity_follows_pm_decision_d1_and_one_table_serves_both_services() -> None:
    """D1: landed (COMEX × USD/INR) is the price of FINE gold; a contract of purity P divides by landed × P / 1000 — GOLD /
    GOLDM 995, GOLDTEN / GOLDPETAL / GOLDGUINEA 999 (never 916). ui-api and data-service read the purity from shared/mcx_specs
    with the same fallback literals."""
    import ast

    from shared import mcx_specs as specs

    assert [gp.fineness_of(c) for c in ("GOLD", "GOLDM", "GOLDTEN", "GOLDPETAL", "GOLDGUINEA")] == [995, 995, 999, 999, 999]
    assert gp.fineness_of("GOLDGU") == 999 and gp.fineness_of("GOLDTE") == 999 and gp.LANDED_FINENESS == 1000
    assert gp.basis_reference("GOLD") == "landed_995" and gp.basis_reference("GOLDGUINEA") == "landed_999"
    assert gp.purity_factor("GOLD") == 0.995 and gp.purity_factor("GOLDPETAL") == 0.999
    # ONE source: shared/mcx_specs (the PM rejected the 916 patch) …
    assert gp.CONTRACT_FINENESS == {f: int(specs.CONTRACTS[f].purity) for f in gp.CONTRACT_FINENESS}
    # … and data-service's ingest_india reads the same spec with the same fallback and the same fine-gold landed (ast only)
    src_path = Path(__file__).resolve().parents[2] / "data-service" / "gold" / "ingest_india.py"
    src = src_path.read_text(encoding="utf-8")
    lits: dict[str, Any] = {}
    for node in ast.parse(src).body:
        target = node.targets[0] if isinstance(node, ast.Assign) else (node.target if isinstance(node, ast.AnnAssign) else None)
        if isinstance(target, ast.Name) and node.value is not None:
            try:
                lits[target.id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    assert lits.get("LANDED_FINENESS") == gp.LANDED_FINENESS and lits.get("_PURITY_FALLBACK") == gp._PURITY_FALLBACK
    assert "specs.CONTRACTS.get(family)" in src and "purity" in src
    a = gp.fair_open(143_237.0, 4077.22, 4077.22, 94.63, 94.63, 15.0, fineness=995)
    b = gp.fair_open(143_237.0, 4077.22, 4077.22, 94.63, 94.63, 15.0, fineness=999)
    assert a["duty_paid_landed"] == b["duty_paid_landed"]                       # the fine-gold price is shared …
    assert a["duty_paid_landed_purity"] == pytest.approx(a["duty_paid_landed"] * 0.995, abs=1)
    assert b["duty_paid_landed_purity"] == pytest.approx(b["duty_paid_landed"] * 0.999, abs=1)
    assert a["basis_pct"] - b["basis_pct"] == pytest.approx(0.40, abs=0.01)      # … the 995 basis sits 0.40 pp higher
    assert a["basis_reference"] == "landed_995" and b["basis_reference"] == "landed_999"
    # negative controls: round 1's conventions give other numbers (999 as the reference; the guinea at 916)
    assert b["basis_pct"] != pytest.approx((143_237.0 / b["duty_paid_landed"] - 1) * 100, abs=0.05)
    g916 = gp.fair_open(143_237.0, 4077.22, 4077.22, 94.63, 94.63, 15.0, fineness=916)
    assert g916["basis_pct"] - b["basis_pct"] > 8.5


def test_overview_prints_one_basis_for_the_picked_contract_on_strip_gauge_and_verdict(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def live(contract: str = "GOLD", expiry: str | None = None) -> dict[str, Any]:
        return {"available": True, "expiry": "2026-10-30", "contract": contract, "as_of": NOW.isoformat(timespec="seconds"),
                "quote": {"ltp": 146_000.0, "source": "ICICI Breeze", "time": NOW.isoformat(timespec="seconds")}}

    monkeypatch.setattr(mcx, "mcx_quote", live)
    o = client.get("/api/gold/overview", params={"contract": "GOLDTEN"}).json()
    s, h = o["strip"], o["health"]
    ib = next(g for g in h["gauges"] if g["key"] == "india_basis")
    h4 = next(c for c in h["verdict"]["clauses"] if c["rule_id"] == "H4")
    assert s["basis_clock"] == "now" == ib["clock"] and s["basis_pct"] == ib["value"] == h4["value"]
    assert s["basis_reference"] == ib["basis_reference"] == "landed_999" and h["fair"]["contract"] == "GOLDTEN"
    assert "999" in h4["text"] and "(live)" in h4["text"]
    # the same live price against the duty-paid landed × 999/1000 (D1: landed is fine gold) …
    assert s["basis_pct"] == pytest.approx((146_000 / (h["fair"]["duty_paid_landed"] * 0.999) - 1) * 100, abs=0.01)
    assert s["basis_pct"] != pytest.approx((146_000 / h["fair"]["duty_paid_landed"] - 1) * 100, abs=0.05)
    # … and /health (GOLD, the WEI / BRF echo) keeps the 995 reference — negative control for the purity switch
    gh = client.get("/api/gold/health").json()
    assert next(g for g in gh["gauges"] if g["key"] == "india_basis")["basis_reference"] == "landed_995"


# ── 7. trend words, the verdict, the partial bar ────────────────────────────────────────────────────────────────────


def test_trend_words_and_the_verdict_clause_print_the_values() -> None:
    assert gold.trend_words(-0.47, -9.72) == "below both averages" and gold.trend_words(0.5, 1.2) == "above both"
    assert gold.trend_words(0.5, -1.0) == "between" and gold.trend_words(-0.5, 1.0) == "between"
    assert gold.trend_words(None, -1.0) is None
    trend = {"key": "trend", "state": "delayed", "change": 4.41, "vs_20d_pct": -0.47, "vs_200d_pct": -9.72, "drawdown_pct": -23.46,
             "trend_words": "below both averages", "window_label": "week to date (since the Fri 30 Oct close)"}
    v = gold.verdict_sentence([trend], "W", {})
    t1 = next(c for c in v["clauses"] if c["rule_id"] == "H1")
    assert t1["text"] == "price below both averages (−0.5 % vs 20-d, −9.7 % vs 200-d; −23.5 % from the 52-w high)".replace("−", "-")
    up = gold.trend_clause_text({"trend_words": "above both", "vs_20d_pct": 1.0, "vs_200d_pct": 5.0, "drawdown_pct": -2.0})
    assert up == "price above both averages (+1.0 % vs 20-d, +5.0 % vs 200-d; -2.0 % from the 52-w high)"
    assert "STRONG WEEK" in v["line"] and "below both averages" in v["line"] and v["line"].endswith(gold.DESCRIBES)
    assert "uptrend" not in v["line"]
    # negative control: a stale trend gauge contributes no clause
    assert not any(c["rule_id"] == "H1" for c in gold.verdict_sentence([{**trend, "state": "stale"}], "W", {})["clauses"])


def test_trend_gauge_serves_the_values_and_the_stores_partial_flag(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    g = next(x for x in client.get("/api/gold/health").json()["gauges"] if x["key"] == "trend")
    for k in ("vs_20d_pct", "vs_200d_pct", "drawdown_pct", "trend_words"):
        assert g[k] is not None, k
    assert g["trend_words"] in ("above both", "between", "below both averages")
    assert g["direction_for_gold"] == f"{gold.TREND_DISPLAY.get(g['trend_words'], g['trend_words'])} (a description)"
    assert "uptrend" not in g["direction_for_gold"]
    assert g["drawdown_pct"] == g["drawdown_52w_pct"] and g["last_bar_partial_source"] == "clock rule"
    real = gold._db_fetch

    async def partial_last(path: str, params: dict[str, Any]) -> Any:
        out = await real(path, params)
        if path == "/db/gold/bars" and params.get("symbol") == gold.GC_FRONT and params.get("interval") == "1d":
            out = json.loads(json.dumps(out))
            rows = out["rows"] if isinstance(out, dict) and "rows" in out else out
            rows[-1]["partial"] = True
        return out

    monkeypatch.setattr(gold, "_db_fetch", partial_last)
    gold._ttl.clear()
    gold.STORE.invalidate()
    g2 = next(x for x in client.get("/api/gold/health").json()["gauges"] if x["key"] == "trend")
    assert g2["last_bar_partial"] is True and g2["last_bar_partial_source"] == "store" and "partial Globex day" in g2["last_bar_note"]


# ── 8. MCXG: the liquid COMEX month, the ticket's margin = the card's ──────────────────────────────────────────────


def test_mcxg_overlay_matches_goldten_nov_to_the_liquid_dec_month(client: TestClient) -> None:
    body = client.get("/api/mcx/overlay", params={"contract": "GOLDTEN", "expiry": "2026-11-30"}).json()
    assert body["overlay"]["comex"]["symbol"] == "GCZ26.CMX" and body["overlay"]["comex"]["calendar_symbol"] == "GCX26.CMX"
    assert "nearest liquid" in body["overlay"]["comex"]["matched_note"] and body["fields"]["comex_symbol"] == "GCZ26.CMX"
    assert "COMEX GCZ26" in body["line"] and "GCX26" not in body["line"]
    # negative control: an even month stays itself, no substitute note
    g = client.get("/api/mcx/overlay", params={"contract": "GOLD"}).json()["overlay"]["comex"]
    assert g["symbol"] == "GCZ26.CMX" and g["matched_note"] is None
    assert gold.comex_liquid_symbol is gp.comex_liquid_symbol                   # ONE helper for GOLD, CONTRACTS and MCXG


def test_the_paper_ticket_margin_equals_the_contract_card(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    row = {"trade_date": "2026-11-05", "exchange": "MCX", "symbol": "GOLDTEN", "expiry": "2026-10-30", "source": "zerodha_nrml",
           "margin_ccy": 13_287.0, "margin_pct": 9.25, "ref_price": 143_650.0}

    async def stored(code: str, expiry: date | None) -> dict[str, Any] | None:
        return row if code == "GOLDTEN" and expiry and expiry.isoformat() == row["expiry"] else None

    monkeypatch.setattr(mcx, "_stored_margin_row", stored)
    spec = mcx.contract_specs()["GOLDTEN"]
    card = mcx.card_margin(spec, 145_750.0, row)
    t1 = client.post("/api/mcx/ticket", json={"contract": "GOLDTEN", "lots": 1, "price": 144_405, "expiry": "2026-10-30"}).json()
    t3 = client.post("/api/mcx/ticket", json={"contract": "GOLDTEN", "lots": 3, "price": 144_405, "expiry": "2026-10-30"}).json()
    assert t1["indicative_margin"] == card["margin_inr"] == 13_287.0 and t3["indicative_margin"] == 3 * 13_287.0
    assert t1["margin_source"] == "zerodha_nrml" and t1["margin_date"] == "2026-11-05" and t1["margin_pct_indicative"] == 9.25
    built = gold.build_contracts(*_family_and_published(), {("GOLDTEN", "2026-10-30"): row}, [], NOW.date())
    ten = next(f for f in built["families"] if f["code"] == "GOLDTEN")["expiries"][0]
    assert ten["margin_inr"] == t1["indicative_margin"] and ten["margin_source"] == t1["margin_source"]
    # negative control: nothing stored → the card's own fallback, the indicative constant on the ticket's notional
    t0 = client.post("/api/mcx/ticket", json={"contract": "GOLDM", "lots": 2, "price": 125_000}).json()
    assert t0["indicative_margin"] == 150_000 and t0["margin_source"].startswith("indicative constant")


def _family_and_published() -> tuple[dict[str, list[dict[str, Any]]], date]:
    got = mcx._master_gold_family()
    assert got is not None
    return got[0], got[1]


# ── 9. events, the WEI line, the brief, Shanghai, MACRO, tender, positioning ───────────────────────────────────────


def test_the_cot_release_is_listed_once_and_mcx_expiries_sit_at_the_session_close() -> None:
    stored = [{"event_date": "2026-11-07", "time_ist": "02:00", "kind": "COT_RELEASE", "name": "CFTC COT (positions as of Tue 03 Nov)",
               "source": "rule+B10"},
              {"event_date": "2026-11-05", "time_ist": "23:30", "kind": "MCX_EXPIRY", "name": "MCX GOLDM Nov-26 expiry"}]
    computed = gold.computed_events(date(2026, 11, 5), 30)
    merged = gold.merge_events(stored, computed)
    cot = [e for e in merged if e["kind"] == "COT_RELEASE" and e["event_date"] == "2026-11-07"]
    assert len(cot) == 1 and cot[0]["source"] == "rule+B10"                     # the stored row wins
    assert len([e for e in merged if e["kind"] == "COT_RELEASE"]) >= 3           # negative control: other weeks kept
    goldm = [e for e in merged if e["kind"] == "MCX_EXPIRY" and "GOLDM" in e["name"] and e["event_date"] == "2026-11-05"]
    assert len(goldm) == 1 and goldm[0]["time_ist"] == "23:55"                   # US standard time: 23:55, not 23:30
    oct_exp = gold.mcx_expiry_time({"event_date": "2026-10-30", "kind": "MCX_EXPIRY", "time_ist": "00:00"})
    assert oct_exp["time_ist"] == "23:30"                                        # US daylight time


def test_the_wei_line_never_cuts_a_word() -> None:
    for head in ("STRONG WEEK, GOLD-SPECIFIC", "STRONG MONTH, DOLLAR-DRIVEN", "SOFT WEEK, YIELD-DRIVEN", "WEAK MONTH, GOLD-SPECIFIC"):
        line = gold.health_line({"headline": head}, [], None)
        words = line.split(" · ")[1]
        assert all(w in head.replace(",", "").split() for w in words.replace(",", "").split()), line
        assert "GOLD-SPECIF " not in line + " " and not line.split(" · ")[1].endswith("-")


def test_an_empty_brief_prints_no_bias_and_trade_prose_is_scrubbed() -> None:
    empty = gold.brief_bias({"bias": "bullish", "confidence": 0.5}, {"synthesis": {"x": 1}})
    assert empty["bias"] is None and empty["confidence"] is None and "no summary, plan or risk list" in empty["bias_withheld"]
    full = gold.brief_bias({"bias": "neutral", "confidence": 0.45}, {"overnight_summary": "Gold rose."})
    assert full["bias"] == "neutral" and full["confidence"] == 0.45 and full["bias_withheld"] is None   # negative control
    doc, found = gold.brief_doc({"doc": {"open_plan": "COMEX rallied overnight. Open signal is aligned_tradeable (deviation ~-100 "
                                                      "vs a 300 threshold), so no wait is required. Watch NFP."}})
    assert "aligned_tradeable" not in json.dumps(doc) and doc["open_plan"] == "COMEX rallied overnight. Watch NFP."
    assert "doc.open_plan (sentence)" in found


def test_shanghai_change_is_vs_the_median_of_previous_pairs_not_one_timing_spike() -> None:
    pts = [{"report_date": d, "value": v} for d, v in
           (("2026-10-27", -2.0), ("2026-10-28", -1.0), ("2026-10-29", -0.5), ("2026-10-30", 75.34), ("2026-11-02", -50.53),
            ("2026-11-03", -1.55))]
    g = gold.shanghai_change({"value": -1.55, "change": -76.89}, pts)
    assert g["change"] == pytest.approx(-1.55 - (-1.0), abs=0.01) and g["median_prev_pairs"] == -1.0
    assert "median of the previous 5" in g["change_window"]
    shifted = [{**p, "value": p["value"] + (30 if i >= 3 else 0)} for i, p in enumerate(pts[:3])] + [
        {"report_date": "2026-11-04", "value": 28.0}]
    assert gold.shanghai_change({"value": 28.0}, shifted)["change"] > 25          # negative control: a real shift shows
    assert gold._timing_spike(pts, 3) is True and gold._timing_spike(pts, 5) is False


def test_macro_units_tags_window_and_rate_horizons(client: TestClient) -> None:
    m = client.get("/api/gold/macro", params={"window": "W"}).json()
    gvz = next(d for d in m["drivers"] if d["key"] == "gvz")
    assert gvz["change_unit"] == "vol pts" and gvz["d1_bp"] is None
    ry = next(d for d in m["drivers"] if d["key"] == "real_10y")
    assert ry["change_unit"] == "bp"                                            # negative control: a yield stays in bp
    h = client.get("/api/gold/health", params={"window": "W"}).json()
    trend = next(g for g in h["gauges"] if g["key"] == "trend")
    assert m["kgx"]["from_date"] == trend["window_from"] and m["kgx"]["window_label"] == trend["window_label"]
    assert all(x["kind"] == "rate horizon" and "not an FOMC date" in x["label"] for x in m["fed"]["meetings"])
    assert m["context"]["hy_oas_unit"] == "%"


def test_stale_macro_driver_gets_no_supportive_word() -> None:
    cat = {"FRED_DCOILBRENTEU": {"verdict": "PUBLISH-CONTEXT", "badge": "context", "max_age_days": 3}}
    old = [{"report_date": (date(2026, 9, 20) + timedelta(days=k)).isoformat(), "value": 100.0 + k, "release_at": None}
           for k in range(26)]  # ends Thu 15 Oct: 11 days before the pinned clock (Mon 26 Oct)
    out = gold.build_macro({"FRED_DCOILBRENTEU": old}, [], [], [], [], None, cat, "W", NOW)
    brent = next(d for d in out["drivers"] if d["series_id"] == "FRED_DCOILBRENTEU")
    assert brent["state"] == "stale" and brent["tag"] is None and "stale" in brent["tag_note"]
    fresh = [{**p, "report_date": (date(2026, 9, 30) + timedelta(days=k)).isoformat()} for k, p in enumerate(old)]
    out2 = gold.build_macro({"FRED_DCOILBRENTEU": fresh}, [], [], [], [], None, cat, "W", NOW)
    assert next(d for d in out2["drivers"] if d["series_id"] == "FRED_DCOILBRENTEU")["tag"] is not None   # negative control


def test_a_running_tender_never_prints_a_negative_count() -> None:
    t = gold.tender_state(date(2026, 11, 1), date(2026, 11, 30), THU)
    assert t["in_tender"] is True and t["days_to_tender"] == 0 and t["tender_note"] == "in tender since Sun 01 Nov (4 d)"
    d = gold.tender_state(date(2026, 12, 1), DEC26, THU)
    assert d["in_tender"] is False and d["days_to_tender"] == 26 and d["tender_note"].startswith("26 days to tender")


def test_mcx_positioning_keeps_oi_on_its_session_and_moves_the_band_to_its_own() -> None:
    """A master published on D: OI at the close of S1 = the session before D (the stored label — data-service matched it to
    Breeze's closing OI), band midpoint = the settlement of the session BEFORE S1. The tape pairs them per session and the
    latest session takes its last-30-min VWAP."""
    def row(stored: str, settle: float, oi: int, release: str | None = None, **kw: Any) -> dict[str, Any]:
        r = {"trade_date": stored, "session_date": stored, "symbol": "GOLD", "expiry": "2026-12-04", "settle": settle,
             "open_interest": oi, "oi_change": None, "source": "icici_master_band", "quality": "proxy", **kw}
        if release:
            r["release_at"] = release
        return r

    rows = [row("2026-10-29", 143_705.0, 15_605), row("2026-11-03", 140_186.0, 16_282),
            row("2026-11-04", BAND_05NOV, 16_110, "2026-11-05T02:00:00+00:00")]
    assert [gold.band_row_session(r) for r in rows] == [date(2026, 10, 28), date(2026, 11, 2), TUE]
    assert gold.band_row_session({**rows[1], "session_date": "2026-11-02"}) == date(2026, 11, 2)   # data-service re-keyed
    assert gold.band_row_session({**rows[1], "source": "bhavcopy"}) == date(2026, 11, 3)           # other sources untouched
    merged = {r["trade_date"]: r for r in gold.mcx_session_rows(rows, [_ok(143_236.8, WED)], "GOLD")}
    assert merged["2026-11-03"]["open_interest"] == 16_282 and merged["2026-11-03"]["settle"] == BAND_05NOV  # OI stays put
    assert merged["2026-11-04"]["open_interest"] == 16_110 and merged["2026-11-04"]["settle_source"] == "breeze_vwap30"
    assert merged["2026-11-02"]["open_interest"] is None and merged["2026-11-02"]["settle"] == 140_186.0
    out = gold.build_positioning_mcx(rows, THU, "GOLD", [_ok(143_236.8, WED)])
    tape = {t["trade_date"]: t for t in out["quadrant_tape"]}
    wed = tape["2026-11-04"]
    assert wed["dprice_pct"] == pytest.approx((143_236.8 / BAND_05NOV - 1) * 100, abs=0.01) and wed["doi"] == -172
    assert wed["label"] == gold.quadrant_label(2.71, -172) and wed["price_source"] == "breeze_vwap30"   # not 'long unwinding'
    tue = tape["2026-11-03"]
    assert tue["dprice_pct"] == pytest.approx((BAND_05NOV / 140_186 - 1) * 100, abs=0.01) and tue["doi"] == 677
    assert tue["label"] is None and "different sessions" in tue["note"]        # price 1 session, OI over the skipped days
    assert tape["2026-11-02"]["price_only"] is True and tape["2026-11-02"]["doi"] is None
    assert out["roll"]["front_oi"] == 16_110                                    # the newest OI session's front
    # negative controls: no VWAP → Wednesday has OI but no price word; a VWAP of another expiry is not this front's price
    bare = {t["trade_date"]: t for t in gold.build_positioning_mcx(rows, THU, "GOLD", None)["quadrant_tape"]}
    assert bare["2026-11-04"]["dprice_pct"] is None and bare["2026-11-04"]["label"] is None
    other = {t["trade_date"]: t for t in gold.build_positioning_mcx(rows, THU, "GOLD", [_ok(143_236.8, WED, expiry=date(2027, 2, 5))])["quadrant_tape"]}
    assert other["2026-11-04"]["dprice_pct"] is None
    need, front = gold.vwap_sessions_needed(rows, "GOLD", WED)
    assert need == [WED] and front == DEC26                                     # Tue is band-covered; Wed needs its VWAP
    need2, _ = gold.vwap_sessions_needed(rows, "GOLD", THU)
    assert need2 == [WED, THU]


def test_official_sector_is_dated_by_its_newest_month() -> None:
    from test_gold_wave1c import _cat

    series = {"IMF_GOLD_OZ_USA": [{"report_date": "2026-07-01", "value": 261_499_000.0, "release_at": None}],
              "IMF_GOLD_OZ_POL": [{"report_date": "2026-09-01", "value": 21_630_000.0, "release_at": None}]}
    out = gold.build_flows([], series, [], [], _cat(), 24)
    assert [o["country"] for o in out["official"]] == ["USA", "POL"]            # sorted by holdings: USA (July) first …
    assert out["official_months"] == {"newest": "2026-09", "oldest": "2026-07"}
    assert out["freshness"]["official"]["as_of"].startswith("2026-09")          # … the panel is dated by the newest month


def test_a_request_never_parks_a_thread_on_a_running_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """While the ONE Breeze read of a key runs, a request waits on the cache with event-loop sleeps (bounded) — no second
    worker thread blocks on the key's lock (the ui-api event-loop rule)."""
    gp._settle_cache.clear()
    started, release = threading.Event(), threading.Event()
    calls: list[int] = []

    def slow(stock: str, expiry: date, session: date) -> tuple[list[dict[str, Any]] | None, str]:
        calls.append(1)
        started.set()
        release.wait(5)
        return _bars(WED), "ok"

    monkeypatch.setattr(gp, "_breeze_session_bars", slow)
    t = threading.Thread(target=gp.session_vwap, args=("GOLD", DEC26, WED))
    t.start()
    assert started.wait(2)
    spawned: list[Any] = []
    real_to_thread = asyncio.to_thread
    monkeypatch.setattr(gp.asyncio, "to_thread", lambda *a, **k: spawned.append(a) or real_to_thread(*a, **k))
    pending = asyncio.run(gp.session_vwap_async("GOLD", DEC26, WED, wait_s=0.3))
    assert pending["status"] == "pending" and spawned == []                    # bounded wait, no thread
    release.set()
    t.join(2)
    done = asyncio.run(gp.session_vwap_async("GOLD", DEC26, WED, wait_s=0.3))
    assert done["status"] == "ok" and len(calls) == 1
    gp._settle_cache.clear()


def test_log_checks_are_read_on_one_thread_and_recorded_beside_the_numbers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real row shape (no `expiry`): the background read asks Breeze for GOLD DEC-26 (the label's expiry) at the LABELLED
    session, records the check and the VWAP beside the numbers and never recomputes error / naive_error."""
    log = tmp_path / "log.json"
    rows = {d: REAL_ROWS[d] for d in ("2026-10-27", "2026-11-05")}
    rows["2026-10-27"] = {**rows["2026-10-27"], "error": 1_060.4}      # a stored figure _update_day would have re-derived
    log.write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setenv("GOLD_LOG_PATH", str(log))
    monkeypatch.setenv("GOLD_SETTLE_BREEZE", "1")
    gp._settle_cache.clear()
    calls: list[tuple[str, date, date]] = []

    def fake(stock: str, expiry: date, session: date) -> tuple[list[dict[str, Any]] | None, str]:
        calls.append((stock, expiry, session))
        if session == WED:
            return _bars(WED), "ok"
        return _flat_bars(session, MEASURED[session]), "ok"    # that session's window at its measured level

    monkeypatch.setattr(gp, "_breeze_session_bars", fake)
    first = gp.log_rows(10, fill_checks=True)
    assert all(r["baseline_check"] is None for r in first)                     # unknown on this call, never guessed
    for _ in range(60):
        stored = json.loads(log.read_text(encoding="utf-8"))
        if all(isinstance(stored[d].get("baseline_check"), dict) for d in rows):
            break
        time.sleep(0.05)
    stored = json.loads(log.read_text(encoding="utf-8"))
    assert sorted(calls, key=lambda c: c[2]) == [("GOLD", DEC26, date(2026, 10, 26)), ("GOLD", DEC26, WED)]
    assert stored["2026-11-05"]["baseline_check"]["flagged"] is True
    assert stored["2026-11-05"]["labelled_session_vwap30"] == pytest.approx(143_236.8, abs=0.1)
    assert stored["2026-11-05"]["labelled_session_vwap30_expiry"] == "2026-12-04"
    assert stored["2026-10-27"]["baseline_check"]["band_vs_vwap30_pct"] == -0.73
    assert stored["2026-11-05"]["error"] == 3_724.0 and stored["2026-11-05"]["naive_error"] == 5_701.0   # nothing re-scored
    assert stored["2026-10-27"]["error"] == 1_060.4                            # never re-derived (it would read 1,060.0)
    again = gp.log_rows(10, fill_checks=True)
    assert all(r["stale_baseline"] for r in again) and len(calls) == 2         # recorded: no second read
    assert again[0]["re_explained"]["error_on_vwap30"] == -114.0              # from the VWAP recorded on the row
    gp._settle_cache.clear()


def test_rows_data_service_already_rekeyed_are_never_shifted_twice() -> None:
    """G-DATA's wave-1d reads re-key `settle` to `settle_session` (= the OI session) and carry the raw band as
    `band_midpoint` / `band_session`: ui-api uses them as they are (no second shift), the raw band only where no settle exists."""
    rk = [
        {"trade_date": "2026-11-03", "symbol": "GOLD", "expiry": "2026-12-04", "open_interest": 16_282, "oi_change": 677,
         "source": "icici_master_band", "settle": BAND_05NOV, "settle_source": "band_midpoint", "settle_quality": "band_proxy",
         "settle_session": "2026-11-03", "band_midpoint": 140_186.0, "band_session": "2026-11-02", "oi_session": "2026-11-03"},
        {"trade_date": "2026-11-04", "symbol": "GOLD", "expiry": "2026-12-04", "open_interest": 16_110, "oi_change": -172,
         "source": "icici_master_band", "settle": 143_236.8, "settle_source": "breeze_vwap30", "settle_quality": "vwap30_proxy",
         "settle_session": "2026-11-04", "band_midpoint": BAND_05NOV, "band_session": "2026-11-03", "oi_session": "2026-11-04"},
    ]
    m = {r["trade_date"]: r for r in gold.mcx_session_rows(rk, None, "GOLD")}
    assert m["2026-11-04"]["settle"] == 143_236.8 and m["2026-11-04"]["settle_source"] == "breeze_vwap30"
    assert m["2026-11-03"]["settle"] == BAND_05NOV and m["2026-11-02"]["settle"] == 140_186.0   # raw band fills Monday only
    tape = {t["trade_date"]: t for t in gold.build_positioning_mcx(rk, THU, "GOLD", None)["quadrant_tape"]}
    assert tape["2026-11-04"]["dprice_pct"] == pytest.approx((143_236.8 / BAND_05NOV - 1) * 100, abs=0.01)
    assert gold.vwap_sessions_needed(rk, "GOLD", WED)[0] == []                 # Wednesday is settled already: no Breeze call
    assert gold.band_row_session(rk[1]) == TUE
    # negative control: the legacy shape (no re-key fields) IS shifted once
    legacy = [{k: v for k, v in r.items() if k not in ("settle_session", "settle_source", "settle_quality", "band_midpoint",
                                                       "band_session", "oi_session")} for r in rk]
    legacy[1]["settle"] = BAND_05NOV
    assert {r["trade_date"]: r for r in gold.mcx_session_rows(legacy, None, "GOLD")}["2026-11-03"]["settle"] == BAND_05NOV


def test_a_vwap_data_service_stored_is_used_without_a_breeze_call(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOLD_STORED_VWAP", "1")          # off under pytest by default (never the live data-service)
    calls: list[Any] = []
    monkeypatch.setattr(gp, "_breeze_session_bars", lambda *a: calls.append(a) or (None, "no_session"))
    real = gold._db_fetch

    async def with_vwap(path: str, params: dict[str, Any]) -> Any:
        if path == "/db/gold/series" and "MCX_GOLD_202612_VWAP30" in str(params.get("ids")):
            return {"series": [{"series_id": "MCX_GOLD_202612_VWAP30",
                                "points": [{"report_date": "2026-10-23", "value": 146_950.0, "release_at": "2026-10-23T18:00:00+00:00"}]}]}
        return await real(path, params)

    monkeypatch.setattr(gold, "_db_fetch", with_vwap)
    gp._settle_cache.clear()
    h = client.get("/api/gold/health").json()["fair"]
    assert h["settlement"] == 146_950.0 and h["settlement_source"] == "breeze_vwap30" and h["settlement_session"] == "2026-10-23"
    assert calls == []                                                          # no Breeze read for a stored session
    assert mcx.vwap30_series_id("GOLDTEN", date(2026, 11, 30)) == "MCX_GOLDTEN_202611_VWAP30"
    gp._settle_cache.clear()


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# ROUND 2 (checker's REJECT + PM decisions D1–D6)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_a_closed_sessions_empty_answer_is_final_and_every_key_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checker minor: a thin back month or an unverified Breeze code used to be re-read every 10 min all night (≈ 144 a day per
    key while CONTRACTS polls). Now: an empty window read > 15 min after the close is kept 8 h, and every key gets at most
    SETTLE_MAX_CALLS calls per 12 h whatever the answers were."""
    gp._settle_cache.clear()
    gp._settle_calls.clear()
    close = gp.session_close_at(WED)
    final = gp.SETTLE_FINAL_MISS_TTL_S
    assert gp.settle_miss_ttl("no_session", close, close + timedelta(hours=1)) == gp.SETTLE_NO_SESSION_TTL_S
    assert gp.settle_miss_ttl("empty", close, close + timedelta(minutes=20)) == final
    assert gp.settle_miss_ttl("no_bars_in_window", close, close + timedelta(minutes=20)) == final
    # negative controls: right after the close the bars may still come; a refusal or an error is retried soon
    assert gp.settle_miss_ttl("empty", close, close + timedelta(minutes=5)) == gp.SETTLE_MISS_TTL_S
    assert gp.settle_miss_ttl("budget", close, close + timedelta(hours=2)) == gp.SETTLE_MISS_TTL_S
    assert gp.settle_miss_ttl("error", close, close + timedelta(hours=2)) == gp.SETTLE_MISS_TTL_S
    ttls: list[tuple[str, float | None]] = []
    real_set = gp._settle_cache.set

    def spy(key: str, value: Any, ttl: float | None = None) -> None:
        ttls.append((value.get("status"), ttl))
        real_set(key, value, ttl=ttl)

    monkeypatch.setattr(gp._settle_cache, "set", spy)
    monkeypatch.setattr(gp, "_now_ist", lambda: close + timedelta(minutes=20))
    calls: list[date] = []
    monkeypatch.setattr(gp, "_breeze_session_bars", lambda s, e, d: (calls.append(d), (None, "empty"))[1])
    gu = ("GOLDGU", date(2026, 11, 30), WED)
    assert gp.session_vwap(*gu)["status"] == "empty" and ttls[-1] == ("empty", final)
    for _ in range(3):                       # the TTL lapses (cleared here): asked again, up to the cap
        gp._settle_cache.clear()
        gp.session_vwap(*gu)
    assert len(calls) == 4
    gp._settle_cache.clear()
    capped = gp.session_vwap(*gu)
    assert capped["status"] == "call_cap" and len(calls) == 4 and ttls[-1] == ("call_cap", final)   # no fifth call
    # negative controls: another key is not capped; a no-session answer made no call and never counts
    gp.session_vwap("GOLDGU", date(2026, 12, 31), WED)
    assert len(calls) == 5
    monkeypatch.setattr(gp, "_breeze_session_bars", lambda s, e, d: (calls.append(d), (None, "no_session"))[1])
    for _ in range(6):
        gp._settle_cache.clear()
        gp.session_vwap("GOLD", DEC26, TUE)
    assert gp._settle_calls.get(gp._settle_key("GOLD", DEC26, TUE), []) == []
    gp._settle_cache.clear()
    gp._settle_calls.clear()


def test_a_vwap_read_before_the_last_bars_is_used_but_not_kept_all_night(monkeypatch: pytest.MonkeyPatch) -> None:
    """Checker minor: a read at 23:57 on lagging bars used to be kept 14 h. Now it is kept 5 min unless its last bar is within
    3 minutes of the close or the read ran 10 minutes after it (the 03 Nov window had 27 bars, so no bar count)."""
    gp._settle_cache.clear()
    gp._settle_calls.clear()
    close = gp.session_close_at(WED)
    ttls: list[tuple[str, float | None]] = []
    real_set = gp._settle_cache.set
    monkeypatch.setattr(gp._settle_cache, "set", lambda k, v, ttl=None: (ttls.append((v.get("status"), ttl)), real_set(k, v, ttl=ttl)))
    part = _flat_bars(WED, 143_000.0, upto_min=15)               # 23:25 … 23:39 only
    monkeypatch.setattr(gp, "_breeze_session_bars", lambda s, e, d: (part, "ok"))
    monkeypatch.setattr(gp, "_now_ist", lambda: close + timedelta(minutes=2))
    r = gp.session_vwap("GOLD", DEC26, WED)
    assert r["status"] == "ok" and r["value"] == 143_000.0 and r["window_complete"] is False
    assert ttls[-1] == ("ok", gp.SETTLE_PARTIAL_TTL_S)
    gp._settle_cache.clear()
    monkeypatch.setattr(gp, "_now_ist", lambda: close + timedelta(minutes=12))      # Breeze had time: final
    assert gp.session_vwap("GOLD", DEC26, WED)["window_complete"] is True and ttls[-1] == ("ok", gp.SETTLE_OK_TTL_S)
    gp._settle_cache.clear()
    monkeypatch.setattr(gp, "_breeze_session_bars", lambda s, e, d: (_bars(WED), "ok"))
    monkeypatch.setattr(gp, "_now_ist", lambda: close + timedelta(minutes=2))       # complete window (last bar 23:54)
    assert gp.session_vwap("GOLD", DEC26, WED)["window_complete"] is True and ttls[-1] == ("ok", gp.SETTLE_OK_TTL_S)
    gp._settle_cache.clear()
    gp._settle_calls.clear()


def test_the_previous_sessions_vwap_stands_in_before_a_two_session_old_band() -> None:
    """Checker minor: after 23:57 with no fresh read, the block fell back to the band (two sessions old) while the previous
    session's VWAP sat in the cache. It is used now, labelled with ITS session."""
    wed = {"status": "ok", **gp.vwap_last_minutes(_bars(WED), gp.session_close_at(WED)), "session": WED.isoformat()}
    b = gp.settlement_block(BAND_05NOV, THU, {"status": "pending"}, THU, wed)
    assert b["settlement"] == pytest.approx(143_236.8, abs=0.1) and b["settlement_source"] == "breeze_vwap30"
    assert b["settlement_session_label"] == "Wed 04 Nov settlement" and b["settlement_is_latest"] is False
    assert "Thu 05 Nov" in b["settlement_note"] and "last-30-min VWAP, proxy" in b["settlement_note"]
    assert b["settlement_check"]["flagged"] is True and "Wed 04 Nov" in b["settlement_check"]["compared"]
    assert b["vwap30"]["session"] == "2026-11-04"
    # negative controls: a latest VWAP wins; a 'previous' result of another session is ignored; never older than the band
    thu = {**wed, "value": 145_000.0, "session": THU.isoformat()}
    assert gp.settlement_block(BAND_05NOV, THU, thu, THU, wed)["settlement"] == 145_000.0
    tue = {**wed, "session": TUE.isoformat()}
    assert gp.settlement_block(BAND_05NOV, THU, {"status": "pending"}, THU, tue)["settlement_source"] == "band_midpoint"
    fri_file = date(2026, 11, 6)                                    # band = Wed 04 Nov; the previous of a Wed latest is Tue
    old = gp.settlement_block(BAND_05NOV, fri_file, {"status": "pending"}, WED, tue)
    assert old["settlement_source"] == "band_midpoint" and old["settlement_session"] == "2026-11-04"


def _stored_vwap_fake(monkeypatch: pytest.MonkeyPatch, value: float = 146_950.0) -> list[str]:
    """data-service answering every MCX_*_VWAP30 id with one point per weekday from 01 Oct to tomorrow (wall clock)."""
    asked: list[str] = []
    real = gold._db_fetch
    days = [date(2026, 10, 1) + timedelta(days=k) for k in range((datetime.now(IST).date() - date(2026, 10, 1)).days + 2)]

    async def fake(path: str, params: dict[str, Any]) -> Any:
        ids = str(params.get("ids") or "")
        if path == "/db/gold/series" and "_VWAP30" in ids:
            asked.append(ids)
            out = [{"series_id": sid, "points": [{"report_date": d.isoformat(), "value": value + (0 if sid.endswith("_VWAP30") else -value + 50),
                                                  "release_at": None} for d in days if d.weekday() < 5]}
                   for sid in ids.split(",") if "_VWAP30" in sid]
            return {"series": out}
        return await real(path, params)

    monkeypatch.setattr(gold, "_db_fetch", fake)
    monkeypatch.setenv("GOLD_STORED_VWAP", "1")
    return asked


def test_every_path_reads_the_stored_vwap_before_breeze(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Checker minor: only /quote's resolve_settlement looked at data-service's stored VWAP30 first; the desk, CONTRACTS and the
    MCX tape went straight to Breeze, so a session G-DATA had read was read twice. One path now (mcx.fill_stored_vwaps)."""
    calls: list[Any] = []
    monkeypatch.setattr(gp, "_breeze_session_bars", lambda *a: calls.append(a) or (None, "no_session"))
    queued: list[Any] = []
    monkeypatch.setattr(gp, "prefetch_session_vwaps", lambda items: queued.extend(items) or 0)
    asked = _stored_vwap_fake(monkeypatch)
    gp._settle_cache.clear()
    # 1. the desk (/fair runs on the wall clock)
    base = client.get("/api/gold/fair").json()["baseline"]
    assert base["value"] == 146_950.0 and base["settlement_source"] == "breeze_vwap30"
    # 2. CONTRACTS: every liquid expiry in ONE stored read, nothing queued for Breeze
    gp._settle_cache.clear()
    n0 = len(asked)
    body = client.get("/api/gold/contracts").json()
    g = next(f for f in body["families"] if f["code"] == "GOLD")
    assert g["expiries"][0]["settle"] == 146_950.0 and g["expiries"][0]["settle_source"] == "breeze_vwap30"
    assert len(asked) == n0 + 1 and queued == []
    # 3. the MCX OI × price tape: the sessions it needs come from the store
    gp._settle_cache.clear()
    monkeypatch.setattr(gold, "vwap_sessions_needed", lambda rows, fam, latest: ([date(2026, 10, 23)], DEC26))
    client.get("/api/gold/positioning/daily", params={"exchange": "MCX"})
    assert gp.session_vwap_cached("GOLD", DEC26, date(2026, 10, 23))["read_by"] == "data-service (stored)"
    assert calls == []                                                         # not one Breeze read on any path
    # negative control: nothing stored → the Breeze path is taken (here: no session) and CONTRACTS queues its reads
    gp._settle_cache.clear()
    mcx._cache.clear()
    monkeypatch.setenv("GOLD_STORED_VWAP", "0")
    client.get("/api/gold/contracts")
    assert queued != []
    gp._settle_cache.clear()


def test_the_physical_ladder_is_per_10_g_for_every_contract(client: TestClient) -> None:
    """D3 / checker major: /premiums?contract=GOLDPETAL printed ₹/1 g landed (12,232) and settle under '₹/10 g' beside the
    IBJA ₹/10 g fix. Every rupee step is ₹/10 g now; the MCX step keeps its native value and unit and says it was scaled."""
    def ladder(contract: str) -> dict[str, dict[str, Any]]:
        body = client.get("/api/gold/premiums", params={"contract": contract}).json()["india"]
        return {s["step"]: s for s in body["ladder"]} | {"_india": body}

    gold_l, petal, guinea = ladder("GOLD"), ladder("GOLDPETAL"), ladder("GOLDGUINEA")
    for lad in (gold_l, petal, guinea):
        assert all(lad[k]["unit"] == "₹/10 g" for k in ("landed", "duty_paid", "mcx"))
    # landed is the fine-gold price per 10 g whatever the contract (the same COMEX and rupee legs in this fixture)
    assert petal["landed"]["value"] == pytest.approx(gold_l["landed"]["value"], abs=10)
    assert guinea["duty_paid"]["value"] == pytest.approx(gold_l["duty_paid"]["value"], abs=10)
    assert petal["landed"]["value"] > 100_000 and guinea["landed"]["value"] > 100_000       # never ₹/1 g or ₹/8 g
    # the MCX settle: band 14,635 per 1 g → 1,46,350 per 10 g; 1,17,100 per 8 g → 1,46,375 per 10 g; said on the label
    assert petal["mcx"]["value"] == 146_350.0 and petal["mcx"]["value_native"] == 14_635.0 and petal["mcx"]["unit_native"] == "₹/1 g"
    assert guinea["mcx"]["value"] == 146_375.0 and guinea["mcx"]["value_native"] == 117_100.0 and guinea["mcx"]["scaled_to_10g"]
    assert "× 10" in petal["mcx"]["label"] and "× 1.25" in guinea["mcx"]["label"]
    assert petal["mcx"]["reference_value"] > 100_000 and "999/1000" in petal["mcx"]["reference_label"]
    assert "scaled × 10" in petal["_india"]["unit_note"]
    # negative control: GOLD is already ₹/10 g — nothing scaled, no note
    assert gold_l["mcx"]["scaled_to_10g"] is False and gold_l["_india"]["unit_note"] is None and "×" not in gold_l["mcx"]["label"].split("settle")[1][:3]


def test_guinea_and_petal_share_the_999_basis(client: TestClient) -> None:
    """D1 / checker major: GOLDGUINEA divided by landed × 0.916 printed +12.05 % against +2.30 % for GOLDTEN. Its ₹/8 g trades
    at the 999 level: the same ₹/10 g price as PETAL gives the same basis."""
    gu = client.get("/api/gold/overview", params={"contract": "GOLDGUINEA"}).json()["strip"]
    pe = client.get("/api/gold/overview", params={"contract": "GOLDPETAL"}).json()["strip"]
    assert gu["basis_reference"] == pe["basis_reference"] == "landed_999" and gu["purity"] == 999
    assert gu["basis_pct"] == pytest.approx(pe["basis_pct"], abs=0.03)            # 1,17,100 / 8 g ≈ 14,635 / g
    assert gu["mcx_quote_unit"] == "₹ per 8 g" and pe["mcx_quote_unit"] == "₹ per 1 g"
    g = client.get("/api/gold/overview").json()["strip"]
    assert g["basis_reference"] == "landed_995"                                   # negative control: GOLD stays 995


def test_the_mcx_chain_names_each_settles_session_and_source(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """D4: every chain settle carries its source and the session it belongs to — the band's own (two before the file), never
    the request date."""
    real = gold._db_fetch
    chain = [{"trade_date": "2026-10-23", "symbol": "GOLD", "expiry": e, "settle": px, "open_interest": oi, "oi_change": None,
              "source": "icici_master_band", "quality": "proxy", "release_at": "2026-10-26T02:00:00+00:00"}
             for e, px, oi in (("2026-12-04", 146_080.0, 16_574), ("2027-02-05", 147_600.0, 519))]

    async def with_chain(path: str, params: dict[str, Any]) -> Any:
        if path == "/db/gold/curve" and params.get("exchange") == "MCX":
            return {"rows": chain}
        return await real(path, params)

    monkeypatch.setattr(gold, "_db_fetch", with_chain)
    body = client.get("/api/gold/curve", params={"exchange": "MCX"}).json()
    assert body["chain_session"] == "2026-10-22" and body["date"] == "2026-10-26"   # the band's session, not the request date
    assert body["points"] and body["chain_session"] and body["chain_session"] != body["date"]
    for p in body["points"]:
        if p["settle_or_last"] is None:
            continue
        assert p["settle_source"] == "band_midpoint" and p["settle_quality"] == "band_proxy"
        assert p["band_session"] == p["settle_session"] == body["chain_session"]
        assert p["settle_session_label"] == body["chain_session_label"]
    # negative control: COMEX points carry no MCX band fields
    cx = client.get("/api/gold/curve", params={"exchange": "COMEX"}).json()
    assert all("band_session" not in p for p in cx["points"])


def test_a_fresher_true_twin_wins_and_says_so() -> None:
    """D6 (G-DATA's patch, applied here): Brent's BZ=F front future replaces FRED's late spot when it is newer; WTI is not a
    stand-in for Brent; DXY vs the Fed broad index is not a twin."""
    cat = {sid: {"verdict": "PUBLISH-CONTEXT", "badge": "context", "max_age_days": 5}
           for sid in ("FRED_DCOILBRENTEU", "BRENT_FRONT", "DXY_CLOSE", "FRED_DTWEXBGS")}

    def pts(last: date, n: int = 30, v0: float = 80.0) -> list[dict[str, Any]]:
        return [{"report_date": (last - timedelta(days=n - 1 - k)).isoformat(), "value": v0 + k * 0.1, "release_at": None}
                for k in range(n)]

    series = {"FRED_DCOILBRENTEU": pts(date(2026, 10, 15)), "BRENT_FRONT": pts(date(2026, 10, 23), v0=70.0),
              "DXY_CLOSE": pts(date(2026, 10, 15), v0=99.0), "FRED_DTWEXBGS": pts(date(2026, 10, 23), v0=120.0)}
    out = gold.build_macro(series, [], [], [], [], None, cat, "W", NOW)
    brent = next(d for d in out["drivers"] if d["key"] == "brent")
    assert brent["series_id"] == "BRENT_FRONT" and "fresher than FRED_DCOILBRENTEU (last 2026-10-15)" in brent["label_note"]
    assert next(d for d in out["drivers"] if d["key"] == "dxy")["series_id"] == "DXY_CLOSE"     # not a twin
    # negative controls: an unpublished twin never replaces a published primary; an older twin loses
    cat2 = {k: v for k, v in cat.items() if k != "BRENT_FRONT"}
    b2 = next(d for d in gold.build_macro(series, [], [], [], [], None, cat2, "W", NOW)["drivers"] if d["key"] == "brent")
    assert b2["series_id"] == "FRED_DCOILBRENTEU" and b2["label_note"] is None
    older = {**series, "BRENT_FRONT": pts(date(2026, 10, 10), v0=70.0)}
    b3 = next(d for d in gold.build_macro(older, [], [], [], [], None, cat, "W", NOW)["drivers"] if d["key"] == "brent")
    assert b3["series_id"] == "FRED_DCOILBRENTEU"
    assert ("brent", "Brent", "FRED_DCOILBRENTEU", "WTI_FRONT", +1, "$/bbl") not in gold.MACRO_DRIVERS


def test_the_trend_sentence_has_its_rule_text_under_h1() -> None:
    """Checker minor: the trend clause reused rule_id H1 while H1's rule only described the week label."""
    h1 = next(r for r in gold.HEALTH_RULES if r["rule_id"] == "H1")
    assert "20-d and 200-d averages" in h1["rule"] and "below both averages" in h1["rule"] and h1["threshold"] == {
        "weak_pct": -2.0, "strong_pct": 2.0, "flat_pct": 0.5}                      # ids / thresholds unchanged (LEARN §8.4)
    trend = {"key": "trend", "state": "delayed", "change": 4.41, "vs_20d_pct": -0.47, "vs_200d_pct": -9.72, "drawdown_pct": -23.46,
             "trend_words": "below both averages", "window_label": "week to date"}
    c = next(x for x in gold.verdict_sentence([trend], "W", {})["clauses"] if x["rule_id"] == "H1")
    assert c["rule_part"].startswith("trend sentence") and c["threshold"] is None
    h4 = next(r for r in gold.HEALTH_RULES if r["rule_id"] == "H4")
    assert "916" not in h4["rule"] and "purity/1000" in h4["rule"]


def test_the_whole_log_on_measured_vwaps_flags_all_seven_mornings_and_reexplains_them(tmp_path: Path,
                                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """Every scored morning of the live log (5 Nov) on the eight labelled-session VWAPs measured on Breeze (G-API 5 Nov round 2:
    09 Oct 1,51,507.1 · 14 Oct 1,45,832.6 · 16 Oct 1,47,911.5 · 22 Oct 1,43,307.9; the other four as above). All seven are
    flagged by BOTH tests; the counterfactual (never the score) puts the model at ≈ ₹330 against the naive ≈ ₹898."""
    rows = {**REAL_ROWS,
            "2026-10-15": {"date": "2026-10-15", "contract": "GOLD DEC-26", "baseline": 148_450.0, "fair_open": 151_000.0,
                           "baseline_source": "MCX settlement 14 Oct (price-band midpoint)", "actual_open": 147_482.0,
                           "error": -3_518.0, "naive_error": -968.0},
            "2026-10-23": {"date": "2026-10-23", "contract": "GOLD DEC-26", "baseline": 146_079.0, "fair_open": 144_938.0,
                           "baseline_source": "MCX settlement 22 Oct (price-band midpoint)", "actual_open": 142_058.0,
                           "error": -2_880.0, "naive_error": -4_021.0}}
    log = tmp_path / "log.json"
    log.write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setenv("GOLD_LOG_PATH", str(log))
    gp._settle_cache.clear()
    measured = {**MEASURED, date(2026, 10, 9): 151_507.1, date(2026, 10, 14): 145_832.6, date(2026, 10, 16): 147_911.5,
                date(2026, 10, 22): 143_307.9}
    for sess, v in measured.items():
        gp._settle_cache.set(gp._settle_key("GOLD", DEC26, sess), _ok(v, sess))
    out = {r["date"]: r for r in gp.log_rows(30)}
    s = gp.accuracy_stats(list(out.values()), 300)
    scored = ["2026-10-12", "2026-10-15", "2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28", "2026-11-05"]
    assert s["days"] == 7 and s["stale_by"]["vwap30_check"] == scored and s["stale_by"]["band_rule"] == scored
    assert s["mean_abs_error"] == pytest.approx(2_141.7, abs=0.1) and s["naive_mean_abs_error"] == pytest.approx(2_071.4, abs=0.1)
    assert s["on_vwap30"]["days"] == 7 and s["on_vwap30"]["mean_abs_error"] == pytest.approx(330.1, abs=0.5)
    assert s["on_vwap30"]["naive_mean_abs_error"] == pytest.approx(898.1, abs=0.5)
    # the 20 Oct row (never scored) moved only 0.29 % on Fri 16 Oct: the VWAP test alone would pass it — the band rule does not
    assert out["2026-10-20"]["baseline_check"]["flagged"] is False and out["2026-10-20"]["stale_reasons"] == ["band_rule", "older_session"]
    gp._settle_cache.clear()
