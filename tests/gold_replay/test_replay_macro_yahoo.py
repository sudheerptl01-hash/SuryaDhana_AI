"""T3 replay — Treasury CSVs, FRED fredgraph bodies, the ForexFactory JSON, GPR, World Bank, the Atlanta Fed workbook
(G-MACRO) and the Yahoo chart bodies saved by G-KITCO (incl. the range=max monthly trap)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from _support import G_KITCO, G_MACRO, read
from gold import db, ingest_macro, ingest_yahoo
from gold.catalog_seed import TREASURY_NOM, TREASURY_REAL, YAHOO_DAILY

DATA, SAMPLES = G_MACRO / "data", G_MACRO / "samples"


def test_treasury_real_and_nominal_23_oct(now):
    real = ingest_macro.parse_treasury_csv(read(DATA / "treasury_real_2026.csv"), TREASURY_REAL, now=now)
    nom = ingest_macro.parse_treasury_csv(read(DATA / "treasury_nominal_2026.csv"), TREASURY_NOM, now=now)
    r = real[real["report_date"] == date(2026, 10, 23)].set_index("series_id")["value"]
    n = nom[nom["report_date"] == date(2026, 10, 23)].set_index("series_id")["value"]
    assert r["UST_REAL_10Y"] == 2.66 and (n["UST_NOM_3M"], n["UST_NOM_2Y"], n["UST_NOM_10Y"], n["UST_NOM_30Y"]) == (4.22, 4.69, 5.00, 5.33)
    assert real["series_id"].nunique() == 5 and len(real) == 5 * 204 and (real["release_source"] == "rule").all()


@pytest.mark.parametrize("name,sid,last_date,last_value", [
    ("fred_DFII10.txt", "FRED_DFII10", date(2026, 10, 22), 2.64), ("fred_DGS2.txt", "FRED_DGS2", None, None),
    ("fred_T10YIE.txt", "FRED_T10YIE", None, None), ("fred_GVZCLS.txt", "FRED_GVZCLS", None, None),
    ("fred_DTWEXBGS.txt", "FRED_DTWEXBGS", date(2026, 10, 16), None), ("fred_M2SL.txt", "FRED_M2SL", None, None),
    ("fred_BAMLH0A0HYM2.txt", "FRED_HY_OAS", date(2026, 10, 22), 3.40), ("fred_EFFR.txt", "FRED_EFFR", None, None),
])
def test_fredgraph_bodies(name, sid, last_date, last_value, now):
    p = SAMPLES / name
    if not p.exists():
        p = DATA / name.replace(".txt", ".csv")
    df = ingest_macro.parse_fredgraph(read(p), sid, freq="D", now=now)
    assert len(df) >= 10 and (df["series_id"] == sid).all() and df["value"].notna().all()
    if last_date:
        assert df["report_date"].max() == last_date
    if last_value is not None:
        assert df.iloc[-1]["value"] == last_value


def test_fred_full_csv_history(now):
    df = ingest_macro.parse_fredgraph(read(DATA / "fred_DFII10.csv"), "FRED_DFII10", freq="D", now=now)
    assert df["report_date"].min() == date(2003, 1, 2) and len(df) > 5900           # '.' rows dropped


def test_forexfactory_this_week_in_ist(now):
    df = ingest_macro.parse_ff_calendar(read(DATA / "ff_calendar_thisweek_2026-10-26.json"), now=now)
    assert (df["country"] == "USD").all() and len(df) >= 20 and df["actual"].isna().all()      # no actual field (j.2 #10)
    fomc = df[df["kind"] == "FOMC"].iloc[0]
    assert (fomc["event_date"], fomc["time_ist"], fomc["forecast"]) == (date(2026, 10, 28), "23:30", "4.00%")
    gdp = df[df["kind"] == "US_GDP"].iloc[0]
    assert (gdp["event_date"], gdp["time_ist"], gdp["in_session"]) == (date(2026, 10, 29), "18:00", True)   # inside the MCX evening
    assert fomc["in_session"] is True or bool(fomc["in_session"])                                            # 23:30 ≤ MCX close 23:30
    assert not df.duplicated(["event_date", "kind", "name"]).any()


def test_gpr_daily_and_monthly(now):
    d = ingest_macro.parse_gpr(read(DATA / "gpr_daily.csv"), daily=True, now=now)
    m = ingest_macro.parse_gpr(read(DATA / "gpr_monthly.csv"), daily=False, now=now)
    assert d[d["report_date"] == date(2026, 10, 19)]["value"].iloc[0] == pytest.approx(248.7, abs=0.1)
    assert m[m["report_date"] == date(2026, 9, 30)]["value"].iloc[0] == pytest.approx(146.2, abs=0.1)
    assert m["report_date"].min() == date(1985, 1, 31) and (m["freq"] == "M").all() and (d["freq"] == "D").all()


def test_worldbank_pink_sheet(now):
    df = ingest_macro.parse_worldbank_monthly(read(DATA / "worldbank_cmo_monthly.csv"), now=now)
    assert df.iloc[0]["report_date"] == date(1960, 1, 31) and df.iloc[0]["value"] == 35.27
    assert df["report_date"].max() == date(2024, 12, 31)                                   # stale vintage (j.2 #12)


def test_atlanta_fed_market_probability_tracker(now):
    df = ingest_macro.parse_atlanta_fed(read(DATA / "atlfed_mpt_histdata.xlsx", binary=True), since=date(2026, 10, 20), now=now)
    row = df[(df["as_of"] == date(2026, 10, 22)) & (df["meeting"] == date(2026, 12, 16))].iloc[0]
    assert row["prob_hike"] == pytest.approx(86.9, abs=0.05) and row["prob_cut"] == pytest.approx(4.5, abs=0.05)
    assert row["rate_mean_bp"] == pytest.approx(417, abs=0.5) and (row["target_lo_bp"], row["target_hi_bp"]) == (375, 400)
    assert row["prob_hold"] == pytest.approx(100 - 86.86 - 4.5, abs=0.05) and row["p10_bp"] < row["rate_mean_bp"] < row["p90_bp"]
    mar = df[(df["as_of"] == date(2026, 10, 22)) & (df["meeting"].astype(str).str.startswith("2027-03"))].iloc[0]
    assert mar["rate_mean_bp"] == pytest.approx(437, abs=1)


def test_yahoo_intraday_bodies_and_the_monthly_trap(now):
    meta, bars = ingest_yahoo.parse_chart(read(G_KITCO / "yahoo_gcf_7d_1m.json"), expect_interval="1m")
    assert meta["dataGranularity"] == "1m" and len(bars) == 6998 and meta["exchangeTimezoneName"] == "America/New_York"
    frame = ingest_yahoo.intraday_frame(bars, "GC=F", "1m", now=now)
    assert frame["ts"].dt.tz is None and frame["ts"].min() < frame["ts"].max() and (frame["interval"] == "1m").all()
    _, b5 = ingest_yahoo.parse_chart(read(G_KITCO / "yahoo_gcf_60d_5m.json"), expect_interval="5m")
    assert len(b5) >= 13000                                     # 17,016 timestamps, bars with a null close dropped
    with pytest.raises(ingest_yahoo.MonthlyTrap):
        ingest_yahoo.parse_chart(read(G_KITCO / "yahoo_gcf_max_1d.json"), expect_interval="1d")


def test_yahoo_daily_csv_seeds_cover_every_catalogued_symbol(store, now):
    files = {p.name[6:-4] for p in DATA.glob("yahoo_*.csv")}
    missing = [sym for sym in (v[0] for v in YAHOO_DAILY.values())
               if sym.replace("=", "_").replace("^", "_").replace(".", "_") not in files and sym not in ("ZQ=F", "CL=F", "DX-Y.NYB", "BZ=F")]
    assert missing == [], missing
    df = ingest_yahoo.parse_daily_csv(read(DATA / "yahoo_GC_F.csv"), "GC=F", now=now)
    # the seed's last row is the Sunday-evening (25 Oct) Globex partial: it belongs to MONDAY's session, never a Sunday row
    assert len(df) == 6564 and df["trade_date"].min() == date(2000, 8, 30) and df["trade_date"].max() == date(2026, 10, 26)
    assert not any(d.weekday() >= 5 for d in df["trade_date"]) and date(2026, 10, 23) in set(df["trade_date"])
    assert ingest_yahoo.ingest_daily(store, df) == 6564 and ingest_yahoo.last_trade_date(store, "GC=F") == date(2026, 10, 26)


def test_in_progress_sunday_globex_bar_is_dated_to_mondays_session_and_replaced_by_the_completed_bar(store, now):
    meta, bars = ingest_yahoo.parse_chart(read(G_KITCO / "yahoo_gcj27_5d_1d.json"), expect_interval="1d")
    assert bars["ts"].iloc[-1].tz_convert("America/New_York").strftime("%a %H:%M") == "Sun 18:19"   # a live quote time, not 00:00
    df = ingest_yahoo.daily_bars_frame(meta, bars, "GCJ27.CMX", now=now)
    assert list(df["trade_date"]) == [date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23), date(2026, 10, 26)]
    assert ingest_yahoo.ingest_daily(store, df) == 5
    # Monday's completed bar (anchored 00:00) arrives under the same key and REPLACES the partial — no Sunday row survives
    done = bars.copy()
    done.loc[done.index[-1], "ts"] = pd.Timestamp("2026-10-26 00:00", tz="America/New_York").tz_convert("UTC")
    done.loc[done.index[-1], "close"] = 4100.0
    ingest_yahoo.ingest_daily(store, ingest_yahoo.daily_bars_frame(meta, done, "GCJ27.CMX", now=now))
    rows = db.query_df(store, "SELECT trade_date, close FROM gold_daily_bars WHERE symbol = 'GCJ27.CMX' ORDER BY trade_date")
    assert len(rows) == 5 and rows["close"].iloc[-1] == 4100.0 and pd.Timestamp(rows["trade_date"].iloc[-1]).date() == date(2026, 10, 26)
    # negative controls: a body whose last bar IS the Friday anchor keeps Friday; a weekday live bar keeps its own day;
    # GLD's 09:30 anchor and GOLDBEES's 09:15 IST anchor are recognised from currentTradingPeriod
    meta_q, bars_q = ingest_yahoo.parse_chart(read(G_KITCO / "yahoo_gcq27_5d_1d.json"), expect_interval="1d")
    assert ingest_yahoo.daily_bars_frame(meta_q, bars_q, "GCQ27.CMX", now=now)["trade_date"].iloc[-1] == date(2026, 10, 23)
    live = bars_q.copy()
    live.loc[live.index[-1], "ts"] = pd.Timestamp("2026-10-23 10:00", tz="America/New_York").tz_convert("UTC")
    assert ingest_yahoo.daily_bars_frame(meta_q, live, "GCQ27.CMX", now=now)["trade_date"].iloc[-1] == date(2026, 10, 23)
    for name, sym, last in (("yahoo_gld_1mo_1d.json", "GLD", date(2026, 10, 23)), ("yahoo_goldbees_1mo_1d.json", "GOLDBEES.NS", date(2026, 10, 23))):
        m, b = ingest_yahoo.parse_chart(read(G_KITCO / name), expect_interval="1d")
        out = ingest_yahoo.daily_bars_frame(m, b, sym, now=now)
        assert out["trade_date"].iloc[-1] == last and not any(d.weekday() >= 5 for d in out["trade_date"])
    assert ingest_yahoo.session_date(date(2026, 10, 24)) == date(2026, 10, 26) and ingest_yahoo.session_date(date(2026, 10, 22)) == date(2026, 10, 22)


def test_per_month_curve_row_from_a_contract_body(store, now):
    meta, bars = ingest_yahoo.parse_chart(read(G_KITCO / "yahoo_gcz26_1d_5m.json"))
    df = ingest_yahoo.curve_frame_from_chart("GCZ26.CMX", meta, bars, store, now=now)
    row = df.iloc[0]
    assert (row["symbol"], row["expiry"], row["quality"], row["source"]) == ("GC", date(2026, 12, 29), "last_trade", "yahoo")   # computed = CME LTD
    assert ingest_yahoo.month_symbol_expiry("GCG27.CMX")[1] == date(2027, 2, 24)
    assert db.upsert(store, "gold_curve", df) == 1


def test_sge_quotations_body_is_dated_by_the_night_session_rule(now):
    from _support import G_CME
    from gold import ingest_physical

    df = ingest_physical.parse_sge_quotations(read(G_CME / "sge_graph_quotations.json"), now=now)
    assert len(df) == 782 and (df["symbol"] == "SGE_AU9999").all()
    assert df["ts"].min() == pd.Timestamp("2026-10-22 12:00") and df["ts"].max() == pd.Timestamp("2026-10-23 07:30")   # Thu 20:00 → Fri 15:30 Beijing
