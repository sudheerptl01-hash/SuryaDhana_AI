"""T2 — the 19 tables, the catalog seed, point-in-time vintages, INSERT OR REPLACE dedupe, proxy/official coexistence,
resampling, memory-bounded batches, Treasury vs FRED same-date equality (PLAN §c.1, §c.2, §h T2)."""
from __future__ import annotations

# ruff: noqa: DTZ001
# (timestamps are UTC-naive by the store's convention)
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from _support import G_COT, G_MACRO, make_store, read
from gold import catalog_seed, db, ingest_cme, ingest_cot, ingest_macro, pit, schema
from gold.schema import BATCH_ROWS, COLUMNS, GOLD_TABLES, PLAN_TABLE_COUNT


def _tables(store) -> set[str]:
    rows = store._conn.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'gold_%'").fetchall()
    return {r[0] for r in rows}


def test_store_init_creates_the_19_plan_tables_and_survives_a_restart(tmp_path):
    s = make_store(tmp_path)
    have = _tables(s)
    assert set(GOLD_TABLES) <= have
    # 19 of PLAN §c.1 + gold_mcx_category_oi counted there as #19 → 20 names, + gold_mcx_daily (O-8, 6 Nov 2026) → 21
    assert len(GOLD_TABLES) == PLAN_TABLE_COUNT + 2 and "gold_mcx_daily" in GOLD_TABLES
    assert "gold_ingest_state" in have and "gold_cot_metrics" in {r[0] for r in s._conn.execute(
        "SELECT table_name FROM information_schema.views").fetchall()}
    s.close()
    s2 = make_store(tmp_path)                                  # restart: IF NOT EXISTS / OR REPLACE, no error
    assert set(GOLD_TABLES) <= _tables(s2)
    schema.ensure_schema(s2)                                   # explicit call is idempotent too
    s2.close()


def test_every_column_in_the_upsert_contract_exists_in_the_table(store):
    for table, cols in COLUMNS.items():
        have = {r[0] for r in store._conn.execute(f"DESCRIBE {table}").fetchall()}
        assert set(cols) == have, table


def test_catalog_seed_is_complete_and_honest(store):
    n = catalog_seed.seed(store)
    rows = catalog_seed.build_rows()
    assert n == len(rows) >= 190
    ids = {r["series_id"] for r in rows}
    for sid in ("COMEX_GC_FRONT", "FRED_DFII10", "UST_REAL_10Y", "GLD_TONNES", "IAU_TONNES", "COT_DISAGG_F", "CME_VOI", "MCX_CURVE_ICICI",
                "IBJA_999_PM", "USDINR_FBIL", "GOLD_IMPORT_DUTY_PCT", "INDIA_PREMIUM_PCT", "MCX_BASIS_PCT", "SHANGHAI_PREMIUM_USD",
                "KGX_USD_EFFECT_PCT", "GSR", "GVZ_SIGMA_DAY_PCT", "ATR14_INR", "WGC_SD_OTC_OTHER", "IMF_GOLD_OZ_CHN", "SGE_SHAU_PM",
                "LBMA_OTC_TURNOVER_USD_BN", "LBMA_VAULT_GOLD_T", "AMFI_GOLD_ETF_AUM_CR", "RBI_GOLD_RESERVES_USD_MN", "SWISS_GOLD_EXPORT_IN_KG",
                "GPR_DAILY", "WB_GOLD_MONTHLY_AVG", "FED_PATH_ATL", "US_CALENDAR_FF", "GOLD_BRIEF", "PREOPEN_LOG"):
        assert sid in ids, sid
    for r in rows:
        assert r["verdict"] in catalog_seed.VERDICTS and r["badge"] in catalog_seed.BADGES, r["series_id"]
        assert r["max_age_days"] > 0 and r["freq"] in ("I", "D", "W", "M", "Q")
    assert not any(r["badge"] == "signal" for r in rows), "no pre-registered study has PASSED as a forecast (G-STUDY)"
    by = {r["series_id"]: r for r in rows}
    assert (by["COMEX_GC_FRONT"]["max_age_days"], by["FRED_DFII10"]["max_age_days"], by["COT_DISAGG_F"]["max_age_days"],
            by["GLD_TONNES"]["max_age_days"], by["WGC_ETF_FLOW_T_GLOBAL"]["max_age_days"], by["IMF_GOLD_OZ_IND"]["max_age_days"],
            by["GOLD_IMPORT_DUTY_PCT"]["max_age_days"]) == (4, 5, 9, 5, 10, 60, 400)
    assert by["COT_DISAGG_F"]["badge"] == "context" and "does not forecast" in by["COT_DISAGG_F"]["verdict_reason"]
    for dormant in ("MCX_BHAVCOPY", "MCX_CATEGORY_OI", "BREEZE_DAILY", "COMEX_WAREHOUSE", "CME_BULLETIN_SETTLE"):
        assert by[dormant]["verdict"] == "LINK-ONLY" and by[dormant]["verdict_reason"]
    assert "attribution" in by["GLD_TONNES"]["terms"].lower() or "display-only" in by["GLD_TONNES"]["terms"]
    assert catalog_seed.seed(store) == n                        # idempotent re-seed


def test_pit_vintage_is_kept_and_a_revision_becomes_a_new_row(store):
    t1 = datetime(2026, 10, 24, 2, 0)
    f = pit.series_frame("FRED_DFII10", [(date(2026, 10, 22), 2.64)], freq="D", source="fred_csv", release_kind="fred_daily", now=t1)
    assert pit.upsert_series(store, f, now=t1) == {"inserted": 1, "revised": 0, "unchanged": 0}
    assert pit.upsert_series(store, f, now=t1 + timedelta(hours=1)) == {"inserted": 0, "revised": 0, "unchanged": 1}
    t2 = datetime(2026, 10, 27, 2, 0)
    f2 = pit.series_frame("FRED_DFII10", [(date(2026, 10, 22), 2.70)], freq="D", source="fred_csv", release_kind="fred_daily", now=t2)
    assert pit.upsert_series(store, f2, now=t2) == {"inserted": 0, "revised": 1, "unchanged": 0}
    rows = db.query_df(store, "SELECT value, revision, release_at FROM gold_series WHERE series_id = 'FRED_DFII10' ORDER BY release_at")
    assert list(rows["revision"]) == [0, 1] and list(rows["value"]) == [2.64, 2.70]
    # as-of before the revision: the vintage; after: the revision — never both
    v_before = pit.asof_series(store, ["FRED_DFII10"], asof=t2 - timedelta(seconds=1))
    v_after = pit.asof_series(store, ["FRED_DFII10"], asof=t2 + timedelta(seconds=1))
    assert len(v_before) == 1 and float(v_before["value"].iloc[0]) == 2.64
    assert len(v_after) == 1 and float(v_after["value"].iloc[0]) == 2.70
    assert pit.latest_asof(store, ["FRED_DFII10"], asof=t1 + timedelta(hours=2))["FRED_DFII10"]["value"] == 2.64
    # release rule: a Friday FRED observation is public on Monday 16:15 ET, never before its own date
    rel = pit.release_rule("fred_daily", date(2026, 10, 23))
    assert rel == datetime(2026, 10, 26, 20, 15)


def test_cot_release_rule_friday_and_the_monday_exceptions():
    assert pit.cot_release_at(date(2026, 10, 20)) == datetime(2026, 10, 23, 19, 30)      # Fri 15:30 ET = 19:30 UTC (EDT)
    assert pit.cot_release_at(date(2026, 11, 10)) == datetime(2026, 11, 16, 20, 30)      # Monday release (EST)
    assert pit.cot_release_at(date(2026, 11, 24)).date() == date(2026, 11, 30)


@pytest.mark.parametrize("rd,rel,src", [
    # the CFTC's published 2026 schedule (G-COT §3.5): every holiday Monday
    (date(2025, 12, 30), date(2026, 1, 5), "published"), (date(2026, 6, 16), date(2026, 6, 22), "published"),
    (date(2026, 6, 30), date(2026, 7, 6), "published"), (date(2026, 11, 10), date(2026, 11, 16), "published"),
    (date(2026, 11, 24), date(2026, 11, 30), "published"), (date(2026, 12, 22), date(2026, 12, 28), "published"),
    # 2025 lapse in appropriations: the verified catch-up table (G-STUDY RELEASE_OVERRIDES)
    (date(2025, 9, 30), date(2025, 11, 19), "verified"), (date(2025, 10, 21), date(2025, 12, 2), "verified"),
    (date(2025, 11, 10), date(2025, 12, 10), "verified"),            # a MONDAY-dated report (Veterans Day Tuesday)
    (date(2025, 12, 23), date(2025, 12, 29), "verified"),
    (date(2025, 1, 7), date(2025, 1, 13), "verified"),               # Carter national day of mourning
    (date(2023, 1, 31), date(2023, 2, 24), "verified"), (date(2023, 3, 14), date(2023, 3, 21), "verified"),   # ION incident
    (date(2018, 12, 24), date(2019, 2, 1), "verified"), (date(2019, 3, 5), date(2019, 3, 8), "verified"),     # 2018-19 lapse
    # October 2013 shutdown: unverifiable → stamped deliberately late
    (date(2013, 10, 1), date(2013, 11, 15), "unverified"), (date(2013, 10, 22), date(2013, 11, 15), "unverified"),
    # the holiday rule for every other year in the data
    (date(2024, 11, 26), date(2024, 12, 2), "rule"),                 # Thanksgiving 28 Nov 2024 → Monday
    (date(2024, 7, 2), date(2024, 7, 8), "rule"),                    # Independence Day on a Thursday → Monday
    (date(2019, 12, 24), date(2019, 12, 30), "rule"),                # Christmas on a Wednesday → Monday
    (date(2021, 6, 15), date(2021, 6, 21), "rule"),                  # Juneteenth 2021 observed Fri 18 Jun → Monday
    (date(2020, 6, 16), date(2020, 6, 19), "rule"),                  # negative control: no Juneteenth before 2021
    (date(2024, 11, 19), date(2024, 11, 22), "rule"),                # negative control: a plain week is the Friday
    (date(2026, 10, 27), date(2026, 10, 30), "rule"),                # the first row of G-COT's remaining-2026 table
])
def test_cot_release_calendar_published_verified_unverified_and_the_holiday_rule(rd, rel, src):
    assert pit.cot_release_date(rd) == (rel, src)
    assert pit.cot_release_at(rd).date() in (rel, rel + timedelta(days=1))          # 15:30 ET is 19:30 / 20:30 UTC
    assert pit.cot_release_source(rd) == ("unverified" if src == "unverified" else "rule")


def test_cot_release_at_is_the_verified_catch_up_instant_in_utc():
    assert pit.cot_release_at(date(2025, 10, 21)) == datetime(2025, 12, 2, 20, 30)       # Tue 2 Dec 2025 15:30 EST
    assert pit.cot_release_at(date(2018, 12, 24)) == datetime(2019, 2, 1, 20, 30)
    assert pit.cot_release_at(date(2013, 10, 8)) == datetime(2013, 11, 15, 20, 30)


def test_ingest_stamps_release_at_and_release_source_point_in_time(store, now):
    raw, typed = ingest_cot.parse_csv_text(read(G_COT / "cot_gold_disagg_futures_only.csv"), "disagg_f", now=now)
    ingest_cot.ingest(store, "disagg_f", raw, typed)
    rows = db.query_df(store, """SELECT report_date, release_at, release_source FROM gold_cot
                                 WHERE contract_code = '088691' AND report = 'disagg' AND fut_or_combined = 'F'""")
    by = {pd.Timestamp(r.report_date).date(): (pd.Timestamp(r.release_at).to_pydatetime(), r.release_source) for r in rows.itertuples(index=False)}
    assert by[date(2025, 10, 21)] == (datetime(2025, 12, 2, 20, 30), "rule")
    assert by[date(2023, 2, 7)] == (datetime(2023, 3, 3, 20, 30), "rule")
    assert by[date(2013, 10, 8)] == (datetime(2013, 11, 15, 20, 30), "unverified")
    assert by[date(2026, 10, 20)] == (datetime(2026, 10, 23, 19, 30), "rule")
    assert sum(1 for _, src in by.values() if src == "unverified") == 4
    # point-in-time: nothing from the 2025 lapse was public before the first catch-up publication (19 Nov 2025)
    leaked = db.scalar(store, """SELECT COUNT(*) FROM gold_cot WHERE report_date BETWEEN DATE '2025-09-30' AND DATE '2025-12-23'
                                 AND release_at < TIMESTAMP '2025-11-19 20:30:00'""")
    assert leaked == 0
    visible = db.scalar(store, "SELECT MAX(report_date) FROM gold_cot WHERE release_at <= TIMESTAMP '2025-11-30 00:00:00'")
    assert pd.Timestamp(visible).date() == date(2025, 10, 14)                          # released 25 Nov; 21 Oct came 2 Dec


def test_release_events_carry_the_monday_dated_report_and_the_ist_instant(now):
    ev25 = ingest_cot.release_events(2025, now=now)
    names = set(ev25["name"])
    assert "CFTC COT (positions as of Tue 11 Nov)" not in names and any("Mon 10 Nov" in n for n in names)
    ev26 = ingest_cot.release_events(2026, now=now)
    row = ev26[ev26["name"].str.contains("10 Nov")].iloc[0]
    assert (row["event_date"], row["time_ist"]) == (date(2026, 11, 17), "02:00")      # Mon 16 Nov 15:30 EST
    assert len(ev26) == 52


def test_insert_or_replace_dedupes_a_refetch(store, now):
    raw, typed = ingest_cot.parse_csv_text(read(G_COT / "cot_gold_disagg_futures_only.csv"), "disagg_f", now=now)
    ingest_cot.ingest(store, "disagg_f", raw, typed)
    n1 = db.scalar(store, "SELECT COUNT(*) FROM gold_cot")
    ingest_cot.ingest(store, "disagg_f", raw, typed)
    assert db.scalar(store, "SELECT COUNT(*) FROM gold_cot") == n1 == 1237
    assert db.scalar(store, "SELECT COUNT(*) FROM gold_cot_raw") == 1237


def test_proxy_and_official_curve_rows_coexist_in_the_key(store, now):
    base = {"trade_date": date(2026, 10, 23), "exchange": "MCX", "symbol": "GOLD", "expiry": date(2026, 12, 4), "settle": 143309.0,
            "unit": "INR/10g", "quality": "proxy", "session_date": date(2026, 10, 23), "release_at": now, "first_seen_at": now,
            "source": "icici_master_band", "band_lo": 139010.0, "band_hi": 147608.0, "open_interest": 16217}
    official = {**base, "source": "mcx_bhavcopy", "quality": "official", "settle": 143250.0, "volume": 12000}
    db.upsert(store, "gold_curve", pd.DataFrame([base]))
    db.upsert(store, "gold_curve", pd.DataFrame([official]))
    rows = db.query_df(store, "SELECT source, quality, settle FROM gold_curve ORDER BY source")
    assert len(rows) == 2 and list(rows["quality"]) == ["proxy", "official"]
    db.upsert(store, "gold_curve", pd.DataFrame([{**base, "settle": 143310.0}]))        # replace, not duplicate
    assert db.scalar(store, "SELECT COUNT(*) FROM gold_curve") == 2


def test_resample_weekly_and_monthly_with_the_bucket_release():
    days = pd.bdate_range("2026-09-28", "2026-10-23")
    pts = pd.DataFrame({"report_date": [d.date() for d in days], "value": [float(i) for i in range(len(days))],
                        "release_at": [datetime(d.year, d.month, d.day, 20, 15) for d in days]})
    w = pit.resample(pts, "W", "last")
    assert [d.isoformat() for d in w["report_date"]] == ["2026-10-02", "2026-10-09", "2026-10-16", "2026-10-23"]
    assert list(w["value"]) == [4.0, 9.0, 14.0, 19.0]
    assert pd.Timestamp(w["release_at"].iloc[-1]) == pd.Timestamp("2026-10-23 20:15")
    s = pit.resample(pts, "W", "sum")
    assert s["value"].iloc[0] == 0 + 1 + 2 + 3 + 4
    m = pit.resample(pts, "M", "mean")
    assert [d.isoformat() for d in m["report_date"]] == ["2026-09-30", "2026-10-31"]
    assert pit.resample(pts, "D").equals(pts)


def test_upsert_batches_never_exceed_50k_rows(store, monkeypatch):
    sizes: list[int] = []
    orig = store._upsert

    def spy(table, df, cols, casts=None):
        sizes.append(len(df))
        return orig(table, df, cols, casts)

    monkeypatch.setattr(store, "_upsert", spy)
    n = BATCH_ROWS * 2 + 7
    df = pd.DataFrame({"symbol": "T", "ts": pd.date_range("2000-01-01", periods=n, freq="min"), "interval": "1m",
                       "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0, "source": "t", "first_seen_at": datetime(2026, 1, 1)})
    assert db.upsert(store, "gold_bars_intraday", df) == n
    assert max(sizes) <= BATCH_ROWS and sum(sizes) == n and len(sizes) == 3


def test_treasury_and_fred_agree_on_the_same_date(now):
    tr = ingest_macro.parse_treasury_csv(read(G_MACRO / "data" / "treasury_real_2026.csv"), {"UST_REAL_10Y": "10 YR"}, now=now)
    fr = ingest_macro.parse_fredgraph(read(G_MACRO / "data" / "fred_DFII10.csv"), "FRED_DFII10", freq="D", now=now)
    j = tr.merge(fr, on="report_date", suffixes=("_t", "_f"))
    assert len(j) > 150
    assert (j["value_t"] - j["value_f"]).abs().max() <= 0.011
    # FRED is the archive one business day later; Treasury the same-day source
    assert fr.loc[fr["report_date"] == date(2026, 10, 22), "release_at"].iloc[0] == datetime(2026, 10, 23, 20, 15)
    assert tr.loc[tr["report_date"] == date(2026, 10, 23), "release_at"].iloc[0] == datetime(2026, 10, 23, 20, 30)


def test_cme_voi_oi_change_is_derived_against_the_prior_stored_day(store, now):
    from _support import G_CME

    ingest_cme.ingest_daily_volume(store, read(G_CME / "daily_volume_20261022.xlsx", binary=True), now=now)
    ingest_cme.ingest_daily_volume(store, read(G_CME / "daily_volume_20261021.xlsx", binary=True), now=now)   # out of order
    rows = db.query_df(store, "SELECT trade_date, open_interest, oi_change FROM gold_cme_daily_voi WHERE product_code = 'GC' ORDER BY trade_date")
    assert list(rows["open_interest"]) == [400390, 403397]
    assert pd.isna(rows["oi_change"].iloc[0]) and rows["oi_change"].iloc[1] == 3007


@pytest.mark.parametrize("kind,rd,expected", [
    ("treasury", date(2026, 10, 23), datetime(2026, 10, 23, 20, 30)),
    ("gld", date(2026, 10, 22), datetime(2026, 10, 23, 0, 30)),
    ("cme_voi", date(2026, 10, 22), datetime(2026, 10, 23, 9, 0)),
    ("sge_pm", date(2026, 10, 23), datetime(2026, 10, 23, 6, 15)),
    ("ibja_pm", date(2026, 10, 23), datetime(2026, 10, 23, 12, 30)),
    ("rbi_wss", date(2026, 10, 16), datetime(2026, 10, 23, 11, 30)),
])
def test_release_rules_are_in_utc(kind, rd, expected):
    assert pit.release_rule(kind, rd) == expected
