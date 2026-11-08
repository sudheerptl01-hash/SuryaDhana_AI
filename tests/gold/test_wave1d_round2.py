"""Wave 1d round 2 (5 Nov 2026, the checker's REJECT + the PM decisions D1–D3) — each rule with a negative control:

1. D1 purity: landed is FINE gold; the stored MCX basis is GOLD (995) vs fine landed × 0.995, the India premium IBJA 999
   vs × 0.999 (``test_derive`` / ``test_wave1d_fixes`` pin the factors); old-pairing basis points are dropped from the
   read once the wave-1d derive has run, never before (point-in-time);
2. the curve reads' ``session_date`` is the session of the SERVED ``settle`` whatever the stored (pre-relabel) value;
3. the VWAP30 job never stores a window whose final minute is not in yet (before close + 10 min), queues it, and the
   next run fetches it; a capped catch-up spends its calls on the fronts first and leaves the rest queued;
4. the settlement block says whether it is the latest completed session, and carries purity / unit / ₹ per 10 g (D3);
5. twins say how they relate (Brent future vs dated spot is a different level); ``meta`` sees per-contract VWAP30 ids;
6. D2: an accuracy-log row without an expiry takes it from its label; every checkable row gets the 0.6 % test."""
from __future__ import annotations

# ruff: noqa: DTZ001
# (timestamps are UTC-naive by the store's convention)
import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from _support import FIXTURES, read
from gold import db, derive, ingest_india, ingest_local, mcx_close, pit, reads

BARS = json.loads(read(FIXTURES / "breeze_mcx_gold_dec26_1m_20261103_04.json"))     # real Breeze 1-min bars, GOLD DEC-26
DEC, FEB, NOV5 = date(2026, 12, 4), date(2027, 2, 5), date(2026, 11, 5)
MON, TUE, WED, THU = date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)
AT_2358_WED = datetime(2026, 11, 4, 18, 28)              # 23:58 IST Wed: the scheduled run, 3 min after the 23:55 close
AT_0015_THU = datetime(2026, 11, 4, 18, 45)              # 00:15 IST Thu: close + 20 min, Breeze's bars are final
AFTER_WED_CLOSE = datetime(2026, 11, 4, 18, 40)          # 00:10 IST Thu
THU_MORNING = datetime(2026, 11, 5, 3, 0)                # 08:30 IST Thu
GRAMS = 31.1034768


def _master_row(trade_date: date, expiry: date, lo: float, hi: float, oi: int, *, symbol: str = "GOLD",
                session_date: date | None = None) -> dict:
    rel = datetime.combine(trade_date + timedelta(days=1), datetime.min.time()) + timedelta(hours=2)        # 07:30 IST next day
    unit = ingest_india.QUOTE_UNIT[symbol]
    return {"trade_date": trade_date, "exchange": "MCX", "symbol": symbol, "expiry": expiry, "settle": round((lo + hi) / 2, 2), "band_lo": lo,
            "band_hi": hi, "open_interest": oi, "unit": unit, "source": "icici_master_band", "quality": "proxy",
            "session_date": session_date or ingest_india.band_session(trade_date), "release_at": rel, "first_seen_at": rel}


@pytest.fixture
def masters(store):
    """The Wed 4 Nov file (OI of Tue 3 Nov, band centred on Mon 2 Nov) and the Thu 5 Nov file (OI of Wed, band centred on Tue)."""
    db.upsert(store, "gold_curve", pd.DataFrame([
        _master_row(TUE, DEC, 135980.0, 144392.0, 16282), _master_row(TUE, FEB, 138638.0, 147214.0, 1180),
        _master_row(WED, DEC, 135269.0, 143635.0, 16110), _master_row(WED, FEB, 137782.0, 146304.0, 0)]))
    return store


def _store_vwap(store, session: date, value: float, *, expiry: date = DEC, family: str = "GOLD", now: datetime | None = None):
    at = now or datetime(2026, 11, 5, 18, 30)
    pit.upsert_series(store, mcx_close.frame(family, expiry, session, {"vwap": value, "lots": 150}, now=at), now=at)


def _bars(store, now):
    for sym, px in (("GC=F", {MON: 3969.6, TUE: 3940.4, WED: 4070.8}), ("INR=X", {MON: 94.55, TUE: 94.6, WED: 94.63})):
        db.upsert(store, "gold_daily_bars", pd.DataFrame([{"trade_date": d, "symbol": sym, "open": c, "high": c, "low": c, "close": c,
                                                           "adj_close": c, "volume": 0, "source": "yahoo", "first_seen_at": now}
                                                          for d, c in px.items()]))


class FakeBreeze:
    """get_historical_data_v2 → the real Breeze bars of the asked day for GOLD DEC-26 (``cut`` drops bars at/after HH:MM)."""

    def __init__(self, cut: str | None = None) -> None:
        self.cut, self.calls = cut, []

    def get_historical_data_v2(self, **kw):
        self.calls.append(kw)
        rows = BARS.get(kw["from_date"][:10], []) if kw["stock_code"] == "GOLD" and kw["expiry_date"].startswith("2026-12-04") else []
        if self.cut:
            rows = [r for r in rows if str(r["datetime"])[11:16] < self.cut]
        return {"Status": 200, "Error": None, "Success": rows}


# ── 1. D1 purity + old-pairing basis points retired from the read (point-in-time) ───────────────────────────────────

def test_old_pairing_basis_points_are_dropped_once_the_new_derive_ran(masters):
    early = datetime(2026, 11, 5, 3, 0)
    _bars(masters, early)
    old = pit.series_frame("MCX_BASIS_PCT", [(TUE, 1.58), (WED, -2.09)], freq="D", source="derived", quality="derived", now=early)
    prem = pit.series_frame("INDIA_PREMIUM_PCT", [(WED, -0.965)], freq="D", source="derived", quality="derived", now=early)
    pit.upsert_series(masters, pd.concat([old, prem], ignore_index=True), now=early)
    before = reads.series(masters, ["MCX_BASIS_PCT"], start=date(2026, 10, 1), asof=early + timedelta(minutes=5))["series"][0]
    assert [p["report_date"] for p in before["points"]] == ["2026-11-03", "2026-11-04"] and before["superseded_points"] == 0   # negative

    run_at = datetime(2026, 11, 5, 18, 0)
    derive.derive_india(masters, now=run_at)
    after = reads.series(masters, ["MCX_BASIS_PCT", "INDIA_PREMIUM_PCT"], start=date(2026, 10, 1), asof=run_at + timedelta(minutes=1))
    basis, india = after["series"]
    by_day = {p["report_date"]: p["value"] for p in basis["points"]}
    # Mon (Tue file's band) and Tue (Wed file's band) re-derived at 995 purity; Wed's −2.09 % artefact has no new value → dropped
    assert sorted(by_day) == ["2026-11-02", "2026-11-03"] and basis["superseded_points"] == 1
    dp_tue = 3940.4 * 94.6 / GRAMS * 10 * 1.15
    assert by_day["2026-11-03"] == pytest.approx((139452.0 / (dp_tue * 0.995) - 1) * 100, abs=0.01)
    assert by_day["2026-11-03"] != pytest.approx(1.58, abs=0.01)                          # the old vintage is superseded
    assert india["superseded_points"] == 0 and [p["report_date"] for p in india["points"]] == ["2026-11-04"]   # no rule: untouched
    # PIT: as of the morning (before the new derive) the read is what it was
    replay = reads.series(masters, ["MCX_BASIS_PCT"], start=date(2026, 10, 1), asof=early + timedelta(minutes=5))["series"][0]
    assert [p["value"] for p in replay["points"]] == [1.58, -2.09]
    assert pit.asof_series(masters, ["MCX_BASIS_PCT"], start=WED)["value"].tolist() == [-2.09]    # stored for audit, never deleted


# ── 2. ``session_date`` follows the served settle, migration-independent ───────────────────────────────────────────

def test_curve_session_date_is_the_session_of_the_served_settle_even_before_the_relabel(store):
    pre = [_master_row(TUE, DEC, 135980.0, 144392.0, 16282, session_date=TUE), _master_row(WED, DEC, 135269.0, 143635.0, 16110, session_date=WED)]
    db.upsert(store, "gold_curve", pd.DataFrame(pre))                                    # written before wave 1d: session_date = trade_date
    hist = {r["trade_date"]: r for r in reads.curve_history(store, exchange="MCX", symbol="GOLD", days=4000)["rows"]}
    tue, wed = hist["2026-11-03"], hist["2026-11-04"]
    assert (tue["settle"], tue["session_date"], tue["settle_session"], tue["band_session"]) == (139452.0, "2026-11-03", "2026-11-03", "2026-11-02")
    assert wed["settle"] is None and wed["session_date"] is None                          # negative control: not the stored '2026-11-04'
    assert tue["settle_inr_per_10g"] == 139452.0
    _store_vwap(store, WED, 143236.81)
    cur = next(r for r in reads.curve(store, exchange="MCX", day=WED)["rows"] if r["expiry"] == "2026-12-04")
    assert (cur["settle"], cur["session_date"], cur["band_session"]) == (143236.81, "2026-11-04", "2026-11-03")
    assert ingest_india.relabel_band_sessions(store) == {"relabelled_dates": 2}            # after the relabel the read is identical
    again = {r["trade_date"]: r for r in reads.curve_history(store, exchange="MCX", symbol="GOLD", days=4000)["rows"]}
    assert {k: (v["settle"], v["session_date"]) for k, v in again.items()} == {"2026-11-03": (139452.0, "2026-11-03"),
                                                                                "2026-11-04": (143236.81, "2026-11-04")}


# ── 3. the VWAP30 job: completeness gate, queue, priority ───────────────────────────────────────────────────────────

def test_a_window_without_its_final_minute_is_not_stored_at_2358_and_the_next_run_fetches_it(masters):
    early = FakeBreeze(cut="23:53")                                                       # the 23:53 and 23:54 bars are not in yet
    res = mcx_close.run(masters, lambda: early, now=AT_2358_WED, pace_s=0, sleep=lambda s: None, backfill_lookback=0)
    c = res["contracts"][0]
    assert (res["status"], res["inserted"], c["status"], c["last_bar"]) == ("ok", 0, "incomplete", "23:52")
    assert mcx_close.stored(masters, "GOLD", DEC, WED) is False and res["queued"] == 1
    assert [(q["session"], q["family"], q["reason"]) for q in mcx_close.load_pending(masters)] == [("2026-11-04", "GOLD", "incomplete")]
    # the 00:15 retry (a run without explicit sessions): Breeze's bars are complete and final → stored, the queue empties
    full = FakeBreeze()
    res2 = mcx_close.run(masters, lambda: full, now=AT_0015_THU, pace_s=0, sleep=lambda s: None, backfill_lookback=0)
    assert res2["inserted"] == 2 and res2["contracts"][0]["complete"] is True and res2["queued"] == 0
    stored = pit.asof_series(masters, [mcx_close.series_id("GOLD", DEC)])
    assert stored["value"].iloc[0] == pytest.approx(143236.8, abs=0.05) and mcx_close.load_pending(masters) == []


def test_a_complete_window_is_stored_at_2358_and_a_thin_one_after_the_final_mark(store):
    db.upsert(store, "gold_curve", pd.DataFrame([_master_row(WED, DEC, 135269.0, 143635.0, 16110)]))
    res = mcx_close.run(store, lambda: FakeBreeze(), now=AT_2358_WED, pace_s=0, sleep=lambda s: None, backfill_lookback=0)
    assert res["inserted"] == 2 and res["contracts"][0]["status"] == "ok" and res["queued"] == 0       # negative control: complete
    thin = mcx_close.run(store, lambda: FakeBreeze(cut="23:50"), now=AT_0015_THU, sessions=[WED], force=True, pace_s=0, sleep=lambda s: None)
    o = thin["contracts"][0]
    assert o["status"] == "ok" and o["complete"] is False and o["last_bar"] == "23:49"   # final: stored as it is, flagged incomplete
    assert mcx_close.window_complete({"last_bar": "23:54"}, mcx_close.session_close(WED))
    assert not mcx_close.window_complete({"last_bar": "23:53"}, mcx_close.session_close(WED))


def test_a_capped_catch_up_spends_its_calls_on_the_fronts_and_the_queue_drains_next_run(masters):
    db.upsert(masters, "gold_curve", pd.DataFrame([_master_row(d, e, 139000.0, 147000.0, oi, symbol="GOLDM")
                                                   for d in (TUE, WED) for e, oi in ((NOV5, 5000), (DEC, 3000))]))
    first = FakeBreeze()
    res = mcx_close.run(masters, lambda: first, now=AFTER_WED_CLOSE, backfill_from=MON, families=["GOLD", "GOLDM"], max_calls=3,
                        pace_s=0, sleep=lambda s: None)
    asked = [(k["stock_code"], k["expiry_date"][:10], k["from_date"][:10]) for k in first.calls]
    # fronts first, GOLD before GOLDM, newest session first — never a far month while a front is missing
    assert res["status"] == "capped" and asked == [("GOLD", "2026-12-04", "2026-11-04"), ("GOLD", "2026-12-04", "2026-11-03"),
                                                   ("GOLD", "2026-12-04", "2026-11-02")]
    assert res["planned"] == 9 and res["queued"] == 6          # Mon: computed fronts; Tue: DEC, FEB, GOLDM ×2; Wed: DEC, GOLDM ×2
    queue = mcx_close.load_pending(masters)
    assert {q["reason"] for q in queue} == {"capped"} and all(q["family"] in ("GOLD", "GOLDM") for q in queue)
    nightly = FakeBreeze()
    res2 = mcx_close.run(masters, lambda: nightly, now=AFTER_WED_CLOSE, pace_s=0, sleep=lambda s: None, backfill_lookback=0)
    assert res2["queued_in"] == 6 and res2["breeze_calls"] == 6 and res2["queued"] == 0              # the queue is drained
    assert [(k["stock_code"], k["from_date"][:10]) for k in nightly.calls][:3] == [("GOLDMI", "2026-11-04"), ("GOLDMI", "2026-11-03"),
                                                                                   ("GOLDMI", "2026-11-02")]
    # negative control: an explicit-sessions run does not drain the queue of other sessions
    mcx_close.save_pending(masters, [mcx_close._queue_item((MON, "GOLDM", NOV5), "capped", 0)], now=AFTER_WED_CLOSE)
    only = FakeBreeze()
    mcx_close.run(masters, lambda: only, now=AFTER_WED_CLOSE, sessions=[WED], families=["GOLD"], force=True, pace_s=0, sleep=lambda s: None)
    assert [k["from_date"][:10] for k in only.calls] == ["2026-11-04"] and len(mcx_close.load_pending(masters)) == 1


def test_errors_stay_queued_until_three_attempts_then_drop(masters):
    class Down(FakeBreeze):
        def get_historical_data_v2(self, **kw):
            self.calls.append(kw)
            return {"Status": 500, "Error": "Internal Server Error", "Success": None}

    for i in range(3):
        res = mcx_close.run(masters, lambda: Down(), now=AFTER_WED_CLOSE + timedelta(minutes=i), pace_s=0, sleep=lambda s: None, backfill_lookback=0)
    assert res["queued"] == 0 and res["dropped_after_errors"] and res["dropped_after_errors"][0]["attempts"] == 3
    assert mcx_close.load_pending(masters) == []
    res = mcx_close.run(masters, lambda: Down(), now=AFTER_WED_CLOSE, pace_s=0, sleep=lambda s: None, backfill_lookback=0)
    assert res["queued"] == 1 and mcx_close.load_pending(masters)[0]["attempts"] == 1               # a fresh failure is queued again


# ── 4. the settlement block: latest session, purity, ₹ per 10 g ──────────────────────────────────────────────────────

def test_settlement_block_says_when_it_is_behind_the_latest_completed_session(masters):
    _store_vwap(masters, TUE, 139448.0)
    s = reads.mcx_settlement(masters, symbol="GOLD", expiry=DEC, day=THU, asof=THU_MORNING)          # the 23:58 Wed run failed
    assert (s["settlement_session"], s["latest_completed_session"], s["settlement_is_latest"], s["settlement_sessions_behind"]) == (
        "2026-11-03", "2026-11-04", False, 1)
    assert s["latest_completed_session_label"] == "Wed 04 Nov settlement"
    _store_vwap(masters, WED, 143236.81)
    s = reads.mcx_settlement(masters, symbol="GOLD", expiry=DEC, day=THU, asof=THU_MORNING)
    assert (s["settlement_session"], s["settlement_is_latest"], s["settlement_sessions_behind"]) == ("2026-11-04", True, 0)
    # negative control (PIT): at 17:30 IST Wed the latest completed session is Tue, so Tue's proxy IS the latest
    early = reads.mcx_settlement(masters, symbol="GOLD", expiry=DEC, day=WED, asof=datetime(2026, 11, 4, 12, 0))
    assert (early["settlement_session"], early["latest_completed_session"], early["settlement_is_latest"]) == ("2026-11-03", "2026-11-03", True)
    # a past ``date`` is judged at the end of that day, not now
    past = reads.mcx_settlement(masters, symbol="GOLD", expiry=DEC, day=TUE, asof=THU_MORNING)
    assert past["latest_completed_session"] == "2026-11-03"
    assert (s["purity"], s["basis_reference"], s["landed_factor"], s["unit"], s["settlement_inr_per_10g"]) == (
        995, "landed_995", 0.995, "INR/10g", 143236.81)


def test_settlement_block_of_a_guinea_is_999_and_scaled_to_10g(masters):
    db.upsert(masters, "gold_curve", pd.DataFrame([_master_row(WED, date(2026, 11, 30), 108000.0, 116422.0, 900, symbol="GOLDGUINEA")]))
    g = reads.mcx_settlement(masters, symbol="GOLDGUINEA", day=THU, asof=THU_MORNING)
    assert (g["unit"], g["quote_grams"], g["purity"], g["basis_reference"]) == ("INR/8g", 8.0, 999, "landed_999")
    assert g["settlement"] == 112211.0 and g["settlement_inr_per_10g"] == pytest.approx(140263.75)
    assert g["landed_factor"] == pytest.approx(0.7992) and g["settlement_inr_per_10g"] != g["settlement"]   # negative: never unscaled


# ── 5. twin relations, meta on per-contract ids ─────────────────────────────────────────────────────────────────────

def test_twins_say_whether_they_are_the_same_level(store):
    asof = datetime(2026, 11, 5, 16, 0)
    pit.upsert_series(store, pit.series_frame("FRED_DCOILBRENTEU", [(TUE, 107.03)], freq="D", source="fred_csv", now=asof), now=asof)
    pit.upsert_series(store, pit.series_frame("FRED_DFII10", [(TUE, 1.71)], freq="D", source="fred_csv", now=asof), now=asof)
    pit.upsert_series(store, pit.series_frame("UST_REAL_10Y", [(WED, 1.74)], freq="D", source="treasury_csv", now=asof), now=asof)
    db.upsert(store, "gold_daily_bars", pd.DataFrame([{"trade_date": WED, "symbol": "BZ=F", "open": 96.99, "high": 96.99, "low": 96.99,
                                                       "close": 96.99, "adj_close": 96.99, "volume": 0, "source": "yahoo",
                                                       "first_seen_at": datetime(2026, 11, 4, 22, 30)}]))
    reads.invalidate_catalog_cache()
    brent, real = reads.series(store, ["FRED_DCOILBRENTEU", "FRED_DFII10"], start=date(2026, 10, 1), asof=asof)["series"]
    assert brent["fresher_twin"]["series_id"] == "BRENT_FRONT" and brent["fresher_twin"]["same_level"] is False
    assert "future" in brent["fresher_twin"]["relation"] and "spot" in brent["fresher_twin"]["relation"]
    assert real["fresher_twin"]["series_id"] == "UST_REAL_10Y" and real["fresher_twin"]["same_level"] is True   # negative control
    assert reads.twin_relation("FRED_DGS2", "GSR") == (None, None)


def test_meta_sees_live_vwap30_ids_and_ignores_expired_months(store, monkeypatch):
    monkeypatch.setattr(reads, "utcnow", lambda: datetime(2026, 11, 20, 6, 0))
    _store_vwap(store, date(2026, 11, 4), 143236.81)                                     # DEC (live): 16 days old > max age → stale
    _store_vwap(store, date(2026, 10, 1), 120000.0, expiry=date(2026, 10, 5))            # OCT-26 expired on 5 Oct → never stale
    reads.invalidate_catalog_cache()
    stale = {r["series_id"] for r in reads.meta(store)["series"]["stale"]}
    assert "MCX_GOLD_202612_VWAP30" in stale and "MCX_GOLD_202612_VWAP30_LOTS" in stale
    assert "MCX_GOLD_202610_VWAP30" not in stale                                         # negative control: an expired month
    reads.invalidate_catalog_cache()


# ── 6. D2: the accuracy log ──────────────────────────────────────────────────────────────────────────────────────────

def test_log_rows_without_an_expiry_take_it_from_the_label_and_every_checkable_row_is_tested(masters, now):
    db.upsert(masters, "gold_curve", pd.DataFrame([_master_row(THU, DEC, 138800.0, 147400.0, 15900)]))   # Fri file: band centred on Wed
    base = {"baseline_source": "MCX settlement (price-band midpoint)", "error": 3256, "naive_error": 5701}
    ingest_local.upsert_preopen_log(masters, {**base, "day": THU, "contract": "GOLD DEC-26", "baseline": 139452.0, "actual_open": 145153.0},
                                    now=now)
    ingest_local.upsert_preopen_log(masters, {**base, "day": WED, "contract": "GOLD DEC-26", "baseline": 140186.0, "actual_open": 140100.0,
                                              "expiry": DEC}, now=now)
    ingest_local.upsert_preopen_log(masters, {**base, "day": TUE, "contract": "GOLDM NOV-26", "baseline": 139000.0, "actual_open": 139500.0},
                                    now=now)
    log = reads.log(masters, days=3650)
    by = {r["day"]: r for r in log["rows"]}
    thu, wed, tue = by["2026-11-05"], by["2026-11-04"], by["2026-11-03"]
    assert (thu["expiry_derived"], thu["expiry_source"]) == ("2026-12-04", "master")    # no expiry stored: from the label + master
    assert (wed["expiry_derived"], wed["expiry_source"]) == ("2026-12-04", "row")
    assert (tue["expiry_derived"], tue["expiry_source"]) == ("2026-11-05", "rule")      # GOLDM: no master row → the exchange rule
    # Thu: no VWAP30 stored → the band centred on Wed (the Fri file, 1,43,100) decides: −2.55 % → flagged
    assert thu["stale_check_source"] == "band_midpoint" and thu["stale_baseline_checked"] is True
    assert thu["baseline_vs_band_pct"] == pytest.approx((139452.0 / 143100.0 - 1) * 100, abs=0.001)
    # Wed: Mon's 1,40,186 vs Tue's band 1,39,452 = +0.53 % — under the 0.6 % rule (negative control: not flagged)
    assert wed["stale_check_source"] == "band_midpoint" and wed["stale_baseline_checked"] is False
    assert not tue.get("stale_check_source") and "stale_baseline_checked" not in tue    # nothing to check against
    assert log["accuracy"]["checked_days_any"] == 2 and log["accuracy"]["stale_days_any"] == 1
    assert log["accuracy"]["unchecked_days"] == ["2026-11-03"]
    assert thu["baseline"] == 139452.0 and thu["error"] == 3256                          # stored numbers are never rewritten
    _store_vwap(masters, WED, 143236.81)
    thu = {r["day"]: r for r in reads.log(masters, days=3650)["rows"]}["2026-11-05"]
    assert thu["stale_check_source"] == "breeze_vwap30" and thu["stale_baseline_vwap30"] is True   # the VWAP30 wins when stored
    acc = reads.log(masters, days=3650)["accuracy"]
    assert acc["checked_days_vwap30"] == 1 and acc["naive_mean_abs_error_stored_same_days"] == 5701.0
    assert acc["naive_mean_abs_error_vwap30"] == pytest.approx(145153.0 - 143236.81, abs=0.01)
