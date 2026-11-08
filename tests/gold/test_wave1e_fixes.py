"""Wave 1e (6 Nov 2026, the final critics C-DATA-3 / C-TRADER-3) on the data-service side — each rule with a negative control:

M-D  the Sun 8 Nov 2026 Muhurat session (14:20–15:30, circular MCX/TRD/590/2026) is a session for the master's session labels
     (previous_mcx_session / band_session), the VWAP30 job (its window is the last 30 minutes, 15:00–15:30, and the Mon–Fri
     23:58 run on Monday also stores Sunday's window) and the OI-delta span count.
M-C  the Shanghai premium is re-derived from the CURRENT legs right after the 03:10 yahoo_daily run (a revised CNY=X bar gave
     a printed pair SGE $4,035.8 − LBMA $4,037.8 = −$2.0 beside a stored +$1.50 for a whole day).
"""
from __future__ import annotations

# ruff: noqa: DTZ001
# (timestamps are UTC-naive by the store's convention)
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import pytest
from gold import db, derive, ingest_india, jobs, mcx_close, pit, reads

FRI, SAT, SUN, MON, TUE = (date(2026, 11, d) for d in (6, 7, 8, 9, 10))
G = 31.1034768


def _utc(d: date, hh: int, mm: int) -> datetime:
    """UTC-naive instant of an IST wall time."""
    return datetime(d.year, d.month, d.day, hh, mm) - timedelta(hours=5, minutes=30)


# ── M-D ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_master_session_labels_count_the_muhurat_sunday():
    assert ingest_india.previous_mcx_session(MON) == SUN                    # the Mon 9 Nov file carries Sunday's OI
    assert ingest_india.band_session(SUN) == FRI                            # … and its band is centred on Friday
    assert ingest_india.previous_mcx_session(TUE) == MON and ingest_india.band_session(MON) == SUN
    # negative controls: an ordinary weekend is skipped; Saturday's file (if any) carries Friday
    assert ingest_india.previous_mcx_session(date(2026, 11, 16)) == date(2026, 11, 13)
    assert ingest_india.previous_mcx_session(SUN) == FRI


def test_the_vwap30_clock_sees_the_short_session():
    assert mcx_close.session_close(SUN).strftime("%H:%M") == "15:30" and mcx_close.session_close(SAT) is None
    assert mcx_close.latest_completed_session(_utc(MON, 8, 45)) == SUN
    assert mcx_close.latest_completed_session(_utc(SUN, 15, 28)) == FRI     # still trading
    assert mcx_close.latest_completed_session(_utc(SUN, 15, 33)) == SUN     # close + the 2-min grace
    assert mcx_close.sessions_between(FRI, MON) == [FRI, SUN, MON]
    bars = [{"datetime": f"2026-11-08 14:{m:02d}:00", "close": 150_000.0, "volume": 4} for m in range(20, 60)] + \
           [{"datetime": f"2026-11-08 15:{m:02d}:00", "close": 151_000.0 + m, "volume": 2} for m in range(30)]
    vw = mcx_close.vwap30(bars, mcx_close.session_close(SUN))
    assert vw["window"] == "15:00–15:30 IST" and vw["bars"] == 30 and vw["vwap"] == pytest.approx(151_014.5, abs=0.01)
    # negative control: the usual evening window is empty on the Sunday
    assert mcx_close.vwap30(bars, datetime(2026, 11, 8, 23, 55, tzinfo=mcx_close.IST)) is None


class _Breeze:
    """get_historical_data_v2 → 30 one-minute bars in the asked session's settlement window (any contract)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_historical_data_v2(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(kw)
        day = date.fromisoformat(kw["from_date"][:10])
        close = mcx_close.session_close(day)
        assert close is not None
        rows = [{"datetime": (close - timedelta(minutes=30 - k)).strftime("%Y-%m-%d %H:%M:%S"), "close": 150_000.0 + day.day,
                 "volume": 5, "open_interest": 100} for k in range(30)]
        return {"Status": 200, "Error": None, "Success": rows}


def test_the_monday_night_run_also_stores_the_muhurat_window(store):
    br = _Breeze()
    res = mcx_close.run(store, lambda: br, now=_utc(MON, 23, 58) + timedelta(minutes=15), families=["GOLD"], pace_s=0,
                        sleep=lambda s: None, backfill_lookback=0)        # the special-session rule alone (sweep off)
    assert res["sessions"] == ["2026-11-08", "2026-11-09"]
    asked = sorted({c["from_date"][:10] for c in br.calls})
    assert asked == ["2026-11-08", "2026-11-09"]
    sun = next(c for c in br.calls if c["from_date"].startswith("2026-11-08"))
    assert sun["from_date"].startswith("2026-11-08T14:50") and sun["to_date"].startswith("2026-11-08T15:34")   # close − 40 → + 4
    assert mcx_close.stored(store, "GOLD", date(2026, 12, 4), SUN) and mcx_close.stored(store, "GOLD", date(2026, 12, 4), MON)
    # a re-run costs nothing (stored sessions are skipped)
    br2 = _Breeze()
    mcx_close.run(store, lambda: br2, now=_utc(MON, 23, 58) + timedelta(minutes=20), families=["GOLD"], pace_s=0,
                  sleep=lambda s: None, backfill_lookback=0)
    assert br2.calls == []


def test_an_ordinary_night_run_stores_only_the_latest_session(store):
    """Steady state: with the recent sessions already stored, a nightly run asks Breeze for the latest session only. (The
    8 Nov 2026 sweep adds a session no run ever stored — see the second half, which is why the store is seeded first.)"""
    night = _utc(date(2026, 11, 16), 23, 58) + timedelta(minutes=15)
    for d in mcx_close.missing_sessions(store, date(2026, 11, 13)):                     # everything before Monday 16 Nov
        mcx_close.run(store, lambda: _Breeze(), now=night, families=["GOLD"], sessions=[d], pace_s=0, sleep=lambda s: None)
    br = _Breeze()
    res = mcx_close.run(store, lambda: br, now=night, families=["GOLD"], pace_s=0, sleep=lambda s: None)
    assert res["sessions"] == ["2026-11-16"] and {c["from_date"][:10] for c in br.calls} == {"2026-11-16"}
    # the sweep itself: drop one stored session and the next ordinary run fetches it again, newest first
    db.execute(store, "DELETE FROM gold_series WHERE series_id LIKE 'MCX_%_VWAP30' AND report_date = ?", [date(2026, 11, 12)])
    br2 = _Breeze()
    res2 = mcx_close.run(store, lambda: br2, now=night, families=["GOLD"], pace_s=0, sleep=lambda s: None)
    assert "2026-11-12" in res2["sessions"]                                             # filled without being asked for
    # negative control: the sweep can be pinned off (the nightly job's old behaviour)
    db.execute(store, "DELETE FROM gold_series WHERE series_id LIKE 'MCX_%_VWAP30' AND report_date = ?", [date(2026, 11, 12)])
    res3 = mcx_close.run(store, lambda: _Breeze(), now=night, families=["GOLD"], pace_s=0, sleep=lambda s: None,
                         backfill_lookback=0)
    assert res3["sessions"] == ["2026-11-16"] and "2026-11-12" not in res3["sessions"]


def test_oi_deltas_spanning_the_muhurat_sunday_count_it():
    assert reads._special_sessions("MCX") == {SUN} and reads._special_sessions("COMEX") == set()
    assert reads.sessions_between(date(2026, 11, 5), SUN, specials={SUN}) == 2           # Fri 6 + Sun 8
    assert reads.sessions_between(date(2026, 11, 5), SUN) == 1                           # negative control: weekday rule only
    assert reads.sessions_between(SUN, MON, specials={SUN}) == 1


# ── M-C ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _cny_bar(store, d: date, close: float, seen: datetime) -> None:
    db.upsert(store, "gold_daily_bars", pd.DataFrame([{"trade_date": d, "symbol": "CNY=X", "open": close, "high": close, "low": close,
                                                       "close": close, "adj_close": close, "volume": 0, "source": "yahoo",
                                                       "first_seen_at": seen}]))


def _legs(store, at: datetime) -> None:
    sge = pit.series_frame("SGE_SHAU_PM", [(date(2026, 11, 4), 865.47)], freq="D", source="sge", quality="official", now=at)
    lb = pit.series_frame("LBMA_PM_USD", [(date(2026, 11, 4), 4037.8)], freq="D", source="wgc", quality="official", now=at)
    pit.upsert_series(store, pd.concat([sge, lb], ignore_index=True), now=at)


def _premium(store, asof: datetime) -> float:
    df = pit.asof_series(store, ["SHANGHAI_PREMIUM_USD"], start=date(2026, 11, 1), asof=asof)
    return float(df[df["report_date"].astype(str).str.startswith("2026-11-04")]["value"].iloc[-1])


def test_a_revised_cny_bar_re_derives_the_shanghai_pair_at_once(store):
    t0 = datetime(2026, 11, 5, 16, 0)                                     # 21:30 IST Thu: the derive_global run
    _legs(store, t0 - timedelta(hours=6))
    _cny_bar(store, date(2026, 11, 4), 6.6643, t0 - timedelta(hours=1))
    first = derive.derive_shanghai(store, now=t0)
    assert first["status"] == "ok"
    assert _premium(store, t0 + timedelta(minutes=1)) == pytest.approx(865.47 * G / 6.6643 - 4037.8, abs=0.01)   # ≈ +1.50
    t1 = datetime(2026, 11, 5, 21, 40)                                    # 03:10 IST Fri: yahoo_daily re-fetches the bar
    _cny_bar(store, date(2026, 11, 4), 6.6701, t1)
    derive.derive_shanghai(store, now=t1 + timedelta(minutes=1))
    now_prem = _premium(store, t1 + timedelta(minutes=2))
    assert now_prem == pytest.approx(865.47 * G / 6.6701 - 4037.8, abs=0.01)                                     # ≈ −2.0
    assert abs(865.47 * G / 6.6701 - 4037.8 - now_prem) < 0.1             # the printed legs reproduce the premium
    # point-in-time: as of Thursday night the first vintage is what was served; a re-run with no change writes nothing
    assert _premium(store, t0 + timedelta(minutes=1)) == pytest.approx(1.50, abs=0.05)
    again = derive.derive_shanghai(store, now=t1 + timedelta(minutes=5))
    assert again.get("inserted", 0) == 0 and again.get("revised", 0) == 0


def test_yahoo_daily_triggers_the_shanghai_re_derive_only_when_cny_was_fetched(store, monkeypatch):
    seen: list[Any] = []
    monkeypatch.setattr(derive, "derive_shanghai", lambda s, now=None: seen.append(now) or {"status": "ok", "inserted": 0})
    monkeypatch.setattr(jobs.ingest_yahoo, "fetch_daily", lambda *a, **k: {"CNY=X": {"status": "ok", "rows": 1}})
    ctx = jobs.Ctx(store=store, http=None, now=datetime(2026, 11, 5, 21, 40))
    out = jobs.g_yahoo_daily(ctx)
    assert out["shanghai_rederive"]["status"] == "ok" and seen == [ctx.now]
    monkeypatch.setattr(jobs.ingest_yahoo, "fetch_daily", lambda *a, **k: {"GC=F": {"status": "ok", "rows": 1}})
    out2 = jobs.g_yahoo_daily(ctx)
    assert "shanghai_rederive" not in out2 and len(seen) == 1             # negative control: no CNY=X, no re-derive
