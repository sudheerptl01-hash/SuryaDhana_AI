"""The derived series are identities over stored rows (SOURCES.md §10 M5–M9, M31, M42, M56, M60): landed and duty-paid
₹/10 g, the India premium, the MCX basis, the KGX split, ratios, the GVZ sigma day, the COMEX carry."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from gold import db, derive, ingest_india, pit

GRAMS = 31.1034768


def _bars(symbol: str, closes: dict[date, float], now: datetime) -> pd.DataFrame:
    return pd.DataFrame([{"trade_date": d, "symbol": symbol, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "adj_close": c,
                          "volume": 0, "source": "yahoo", "first_seen_at": now} for d, c in closes.items()])


@pytest.fixture
def seeded(store, now):
    days = [date(2026, 10, 19) + timedelta(days=i) for i in range(5)]
    gc = {d: 4000.0 + 10 * i for i, d in enumerate(days)}
    for sym, px in (("GC=F", gc), ("INR=X", dict.fromkeys(days, 95.0)), ("SI=F", dict.fromkeys(days, 50.0)), ("PL=F", dict.fromkeys(days, 1600.0)),
                    ("^GVZ", dict.fromkeys(days, 24.15)), ("EURUSD=X", {d: 1.10 + 0.001 * i for i, d in enumerate(days)}),
                    ("JPY=X", dict.fromkeys(days, 150.0)), ("GBPUSD=X", dict.fromkeys(days, 1.30)), ("CAD=X", dict.fromkeys(days, 1.38)),
                    ("SEK=X", dict.fromkeys(days, 10.5)), ("CHF=X", dict.fromkeys(days, 0.88)), ("CNY=X", dict.fromkeys(days, 7.0))):
        db.upsert(store, "gold_daily_bars", _bars(sym, px, now))
    pit.upsert_series(store, pit.series_frame("IBJA_999_PM", [(days[-1], 141630.0)], freq="D", source="t", now=now), now=now)
    pit.upsert_series(store, pit.series_frame("SGE_SHAU_PM", [(days[-1], 862.76)], freq="D", source="t", now=now), now=now)
    pit.upsert_series(store, ingest_india.duty_frame(now=now), now=now)
    db.upsert(store, "gold_curve", pd.DataFrame([
        {"trade_date": days[-1], "exchange": "MCX", "symbol": "GOLD", "expiry": date(2026, 12, 4), "settle": 146079.0, "unit": "INR/10g",
         "source": "icici_master_band", "quality": "proxy", "session_date": days[-1], "release_at": now, "first_seen_at": now},
        {"trade_date": days[-1], "exchange": "COMEX", "symbol": "GC", "expiry": date(2026, 12, 29), "settle": 4007.9, "unit": "USD/oz",
         "source": "yahoo", "quality": "last_trade", "session_date": days[-1], "release_at": now, "first_seen_at": now},
        {"trade_date": days[-1], "exchange": "COMEX", "symbol": "GC", "expiry": date(2027, 2, 24), "settle": 4041.3, "unit": "USD/oz",
         "source": "yahoo", "quality": "last_trade", "session_date": days[-1], "release_at": now, "first_seen_at": now}]))
    return store, days


def test_derive_india_identities(seeded, now):
    store, days = seeded
    res = derive.derive_india(store, now=now)
    assert res["status"] == "ok" and res["duty_pct"] == 15.0
    v = pit.latest_asof(store, ["GOLD_INR_LANDED", "GOLD_INR_DUTY_PAID", "INDIA_PREMIUM_PCT", "MCX_BASIS_PCT", "MCX_BASIS_CARRY_ADJ_PCT"])
    landed = 4040.0 * 95.0 / GRAMS * 10
    assert v["GOLD_INR_LANDED"]["value"] == round(landed) and v["GOLD_INR_DUTY_PAID"]["value"] == round(landed * 1.15)
    dp = round(landed * 1.15)
    # PM decision D1 (wave 1d round 2): landed is the price of FINE gold, so IBJA 999 compares with duty-paid × 0.999
    assert v["INDIA_PREMIUM_PCT"]["value"] == pytest.approx((141630.0 / (dp * 0.999) - 1) * 100, abs=0.01)
    assert v["INDIA_PREMIUM_PCT"]["value"] != pytest.approx((141630.0 / (dp * 999 / 995) - 1) * 100, abs=0.1)   # negative: the old 999/995
    # wave 1d: the master row keyed Fri 23 Oct carries the band of Thu 22 Oct's settlement, so the basis is dated 22 Oct
    # and divides by 22 Oct's duty-paid landed price (GC 4,030) at GOLD's 995 purity, never 23 Oct's (the old pairing)
    dp_thu = 4030.0 * 95.0 / GRAMS * 10 * 1.15
    basis = pit.asof_series(store, ["MCX_BASIS_PCT"])
    assert [db.to_date(d) for d in basis["report_date"]] == [days[-2]] and basis["quality"].iloc[-1] == "derived_band"
    assert v["MCX_BASIS_PCT"]["value"] == pytest.approx((146079.0 / (dp_thu * 0.995) - 1) * 100, abs=0.01)
    assert v["MCX_BASIS_PCT"]["value"] != pytest.approx((146079.0 / dp_thu - 1) * 100, abs=0.1)        # negative control: 995 as reference
    assert v["MCX_BASIS_PCT"]["value"] != pytest.approx((146079.0 / (dp * 0.995) - 1) * 100, abs=0.01)  # negative control: old pairing
    carry = derive.CARRY_RATE_PCT * (date(2026, 12, 4) - days[-2]).days / 365
    assert v["MCX_BASIS_CARRY_ADJ_PCT"]["value"] == pytest.approx(v["MCX_BASIS_PCT"]["value"] - carry, abs=0.01)
    assert ingest_india.duty_on(date(2026, 5, 12)) == (6.0, date(2024, 7, 24)) and ingest_india.duty_on(date(2026, 5, 13))[0] == 15.0


def test_derive_global_identities(seeded, now):
    store, _days = seeded
    res = derive.derive_global(store, now=now)
    assert res["status"] == "ok"
    v = pit.latest_asof(store, ["GSR", "GPR_RATIO", "GVZ_SIGMA_DAY_PCT", "GOLD_IN_EUR", "GOLD_IN_JPY", "GOLD_IN_CNY", "KGX_USD_EFFECT_PCT",
                               "KGX_PURE_GOLD_PCT", "KGX_INR_EFFECT_PCT", "SHANGHAI_PREMIUM_USD", "SHANGHAI_PREMIUM_PCT", "COMEX_CARRY_ANN_PCT"])
    assert v["GSR"]["value"] == pytest.approx(4040 / 50, abs=0.001) and v["GPR_RATIO"]["value"] == pytest.approx(4040 / 1600, abs=0.001)
    assert v["GVZ_SIGMA_DAY_PCT"]["value"] == pytest.approx(24.15 / math.sqrt(252), abs=0.001)      # 1.52 % (SOURCES A6)
    assert v["GOLD_IN_EUR"]["value"] == pytest.approx(4040 / 1.104, abs=0.01) and v["GOLD_IN_JPY"]["value"] == pytest.approx(4040 * 150, abs=0.01)
    assert v["GOLD_IN_CNY"]["value"] == pytest.approx(4040 * 7 / GRAMS, abs=0.001)
    total = math.log(4040 / 4030) * 100
    usd = 0.576 * math.log(1.104 / 1.103) * 100                      # only EUR moved on the last day
    assert v["KGX_USD_EFFECT_PCT"]["value"] == pytest.approx(usd, abs=0.002)
    assert v["KGX_PURE_GOLD_PCT"]["value"] + v["KGX_USD_EFFECT_PCT"]["value"] == pytest.approx(total, abs=0.003)
    assert v["KGX_INR_EFFECT_PCT"]["value"] == 0.0
    sge_usd = 862.76 * GRAMS / 7.0
    assert v["SHANGHAI_PREMIUM_USD"]["value"] == pytest.approx(sge_usd - 4040, abs=0.02)
    assert v["COMEX_CARRY_ANN_PCT"]["value"] == pytest.approx((4041.3 / 4007.9 - 1) * 365 / 57 * 100, abs=0.01)   # ≈5.3 % p.a. (SOURCES A2)


def test_derive_without_inputs_is_honest(store, now):
    assert derive.derive_india(store, now=now)["status"] == "no_inputs"
    assert derive.derive_global(store, now=now)["status"] == "no_inputs"
