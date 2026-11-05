"""T3 replay — CFTC COT (JSON scratch + CSV seeds) and the CME FTP files saved by G-CME: daily volume & OI (ten dated
xlsx), EFRP, the product calendar XML, the product reference zip. Every assertion is a number quoted in SOURCES.md."""
from __future__ import annotations

from datetime import date
from typing import ClassVar

import pandas as pd
import pytest
from _support import G_CME, G_COT, G_STUDY, read
from gold import db, ingest_cme, ingest_cot

VOI_FILES = sorted(G_CME.glob("daily_volume_2026*.xlsx"))


def test_cot_json_scratch_body_parses_with_every_cftc_typo(now):
    raw, typed = ingest_cot.parse_json_text(read(G_COT.parent / "scratch" / "api_gold_72hh-3qpy.json"), "disagg_f", now=now)
    assert set(typed["contract_code"]) <= {"088691", "088695", "088LM1"} and len(typed) == len(raw) >= 1
    gold = typed[typed["contract_code"] == "088691"].sort_values("report_date").iloc[-1]
    assert gold["open_interest"] == 402279 and gold["mm_long"] == 120970 and raw["id"].str.endswith("F").all()
    assert gold["conc_net4_short"] == pytest.approx(36.5, abs=0.2)   # top-4 net short 36.5 % (SOURCES B3)


def test_cot_csv_seeds_cover_the_published_history(now):
    for ds, f, n_gold, first in (("disagg_f", "cot_gold_disagg_futures_only.csv", 1063, date(2006, 6, 13)),
                                 ("disagg_c", "cot_gold_disagg_combined.csv", 1063, date(2006, 6, 13)),
                                 ("legacy_f", "cot_gold_legacy_futures_only.csv", 1939, date(1986, 1, 15)),
                                 ("legacy_c", "cot_gold_legacy_combined.csv", 1648, date(1995, 3, 21))):
        _raw, typed = ingest_cot.parse_csv_text(read(G_COT / f), ds, now=now)
        g = typed[typed["contract_code"] == "088691"]
        assert len(g) == n_gold and g["report_date"].min() == first and g["report_date"].max() == date(2026, 10, 20), ds
    # the G-STUDY copy of the same dataset agrees row for row with the G-COT copy (two independent pulls)
    _, a = ingest_cot.parse_csv_text(read(G_COT / "cot_gold_disagg_futures_only.csv"), "disagg_f", now=now, codes=("088691",))
    _, b = ingest_cot.parse_csv_text(read(G_STUDY / "cftc_socrata_disagg_fut_gold_088691.csv"), "disagg_f", now=now, codes=("088691",))
    j = a.merge(b, on="report_date", suffixes=("_a", "_b"))
    assert len(j) == 1063 and (j["mm_long_a"] == j["mm_long_b"]).all() and (j["open_interest_a"] == j["open_interest_b"]).all()


def test_daily_volume_xlsx_22_oct(now):
    df = ingest_cme.parse_daily_volume(read(G_CME / "daily_volume_20261022.xlsx", binary=True), now=now)
    assert (df["trade_date"] == date(2026, 10, 22)).all() and (df["exchange"] == "COMEX").all()
    oi = {(r.product_code, r.fut_or_opt): r.open_interest for r in df.itertuples(index=False)}
    assert oi[("GC", "F")] == 403397 and oi[("MGC", "F")] == 124151 and oi[("1OZ", "F")] == 87158 and oi[("QO", "F")] == 8551
    assert oi[("OG", "C")] == 631061 and oi[("OG", "P")] == 259338 and oi[("SI", "F")] == 114637
    gc = df[(df["product_code"] == "GC") & (df["fut_or_opt"] == "F")].iloc[0]
    assert (gc["globex_volume"], gc["otc_volume"], gc["total_volume"]) == (237695, 8324, 246019)
    assert gc["release_at"] == pd.Timestamp("2026-10-23 09:00")           # T+1 ≈ 14:30 IST


def test_ten_dated_voi_files_replay_and_the_oi_change_heals_out_of_order(store, now):
    assert len(VOI_FILES) >= 9
    for p in reversed(VOI_FILES):                                            # newest first: out of order on purpose
        ingest_cme.ingest_daily_volume(store, read(p, binary=True), now=now)
    rows = db.query_df(store, "SELECT trade_date, open_interest, oi_change FROM gold_cme_daily_voi WHERE product_code = 'GC' AND fut_or_opt = 'F' ORDER BY trade_date")
    assert len(rows) == len(VOI_FILES) and rows["trade_date"].iloc[-1] == pd.Timestamp("2026-10-22")
    diffs = rows["open_interest"].diff()
    assert (rows["oi_change"].iloc[1:].to_numpy() == diffs.iloc[1:].to_numpy()).all()
    cross = db.scalar(store, "SELECT open_interest FROM gold_cme_daily_voi WHERE product_code = 'GC' AND fut_or_opt = 'F' AND trade_date = DATE '2026-10-20'")
    assert abs(cross - 402279) / 402279 < 0.001                               # CFTC Tuesday OI 402,279 vs the file's 402,507 (0.06 %)


def test_backfill_runner_is_resumable_and_paced(store, now):
    bodies = {p.name[13:21]: read(p, binary=True) for p in VOI_FILES}
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        day = url.rsplit("_", 1)[-1][:8]
        fetched.append(day)
        if day not in bodies:
            raise RuntimeError("550 No such file")
        return bodies[day]

    weekdays = [date(2026, 10, 9) + __import__("datetime").timedelta(days=i) for i in range(14)]
    weekdays = [d for d in weekdays if d.weekday() < 5]                       # 10 weekdays, 9 Oct → 22 Oct
    res = ingest_cme.backfill_daily_volume(store, date(2026, 10, 9), date(2026, 10, 22), fetch=fetch, now=now)
    assert res["files"] == len(VOI_FILES)
    assert res["errors"] == []
    assert res["missing_count"] == len(weekdays) - len(VOI_FILES)              # the 550s are holidays/missing, not errors
    assert res["remaining"] == 0 and len(fetched) == len(weekdays)
    n1 = len(fetched)
    res2 = ingest_cme.backfill_daily_volume(store, date(2026, 10, 9), date(2026, 10, 22), fetch=fetch, now=now)
    assert res2["files"] == 0                                                   # resumable: nothing re-downloaded
    assert res2["skipped_existing"] == len(VOI_FILES)
    assert len(fetched) == n1 + res2["missing_count"]                           # only the still-missing days are retried
    assert fetched[n1:] == sorted(d.strftime("%Y%m%d") for d in weekdays if d.strftime("%Y%m%d") not in bodies)


def test_ftp_fetch_paces_one_file_per_two_seconds_with_the_allowlisted_host(monkeypatch):
    """The pacing lives in hosts.ftp_fetch (the backfill runner injects it): every call sleeps FTP_GAP_S before RETR."""
    from gold import hosts

    class StubFTP:
        logins: ClassVar[list[str]] = []
        retrs: ClassVar[list[str]] = []

        def __init__(self, host, timeout=None):
            StubFTP.logins.append(host)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self):
            pass

        def retrbinary(self, cmd, sink, blocksize=65536):
            StubFTP.retrs.append(cmd)
            sink(b"x" * 10)
            sink(b"y" * 5)

    slept: list[float] = []
    monkeypatch.setattr(hosts.ftplib, "FTP", StubFTP)
    body = hosts.ftp_fetch(ingest_cme.FTP_VOI_ARCHIVE.format(yyyymmdd="20261021"), sleep=slept.append)
    body2 = hosts.ftp_fetch(ingest_cme.FTP_EFRP_LATEST, sleep=slept.append)
    assert body == b"x" * 10 + b"y" * 5 and body2 == body
    assert slept == [hosts.FTP_GAP_S, hosts.FTP_GAP_S] and hosts.FTP_GAP_S == 2.0
    assert StubFTP.logins == ["ftp.cmegroup.com", "ftp.cmegroup.com"] and StubFTP.retrs[0] == "RETR /daily_volume/daily_volume_20261021.xlsx"
    with pytest.raises(RuntimeError, match="exceeds"):                         # the size bound still holds with the stub
        hosts.ftp_fetch(ingest_cme.FTP_VOI_LATEST, sleep=slept.append, max_bytes=12)
    with pytest.raises(hosts.HostNotAllowed):                                  # negative control: no sleep, no socket for a foreign host
        hosts.ftp_fetch("ftp://ftp.example.org/daily_volume.xlsx", sleep=slept.append)
    assert len(slept) == 3 and len(StubFTP.logins) == 3


def test_cot_raw_payload_is_replaced_not_versioned(store, now):
    """gold_cot_raw keys on (dataset, id): a republished week overwrites the stored payload (the docstring says so now)."""
    raw, typed = ingest_cot.parse_json_text(read(G_COT.parent / "scratch" / "api_gold_72hh-3qpy.json"), "disagg_f", now=now)
    ingest_cot.ingest(store, "disagg_f", raw, typed)
    n = db.scalar(store, "SELECT COUNT(*) FROM gold_cot_raw")
    raw2 = raw.copy()
    raw2["payload"] = raw2["payload"].str.replace("402279", "402280")
    ingest_cot.ingest(store, "disagg_f", raw2, typed)
    assert db.scalar(store, "SELECT COUNT(*) FROM gold_cot_raw") == n
    assert db.scalar(store, "SELECT COUNT(*) FROM gold_cot_raw WHERE payload::VARCHAR LIKE '%402280%'") >= 1
    assert db.scalar(store, "SELECT COUNT(*) FROM gold_cot_raw WHERE payload::VARCHAR LIKE '%402279%'") == 0


def test_efrp_csv_23_oct(now):
    df = ingest_cme.parse_efrp(read(G_CME / "efrp-report_20261023.csv"), now=now)
    assert len(df) == 19 and df["round_turns"].sum() == 3115 and set(df["contract_expiry"]) == {"2026-12"}
    assert set(df["txn_type"]) == {"EFP"} and (df["process_date"] == date(2026, 10, 23)).all() and (df["product"] == "GOLD").all()
    assert df["row_no"].max() == 19 and df["row_no"].is_unique


def test_product_calendar_xml_streams_304_contracts(store, now):
    df = ingest_cme.parse_product_calendar(str(G_CME / "product-calendar-new.xml"), now=now)
    assert len(df) == 304 and (df["as_of"] == date(2026, 10, 23)).all()
    gcz6 = df[(df["symbol"] == "GC") & (df["mmy"] == "202612")].iloc[0]
    assert (gcz6["first_intent"], gcz6["first_notice"], gcz6["last_trade"], gcz6["ltd_end_time"]) == (
        date(2026, 11, 27), date(2026, 11, 30), date(2026, 12, 29), "12:30:00 PM")
    assert (gcz6["first_delivery"], gcz6["last_delivery"], gcz6["last_notice"]) == (date(2026, 12, 1), date(2026, 12, 31), date(2026, 12, 30))
    gcg7 = df[(df["symbol"] == "GC") & (df["mmy"] == "202702")].iloc[0]
    assert (gcg7["first_notice"], gcg7["last_trade"]) == (date(2027, 1, 29), date(2027, 2, 24))
    for sym in ("1OZ", "QO"):
        assert df[(df["symbol"] == sym) & (df["mmy"] == "202612")].iloc[0]["last_trade"] == date(2026, 11, 25)
    res = ingest_cme.ingest_product_calendar(store, str(G_CME / "product-calendar-new.xml"), now=now)
    assert res["rows"] == 304 and db.scalar(store, "SELECT COUNT(*) FROM gold_cme_calendar") == 304
    assert db.scalar(store, "SELECT COUNT(DISTINCT symbol) FROM gold_cme_calendar WHERE symbol LIKE 'GC:OOF:%'") >= 3   # weekly option roots kept apart


def test_product_reference_zip_and_margins(store, now):
    df = ingest_cme.parse_prf(read(G_CME / "cmeg.comex.fut.prf.csv.zip", binary=True), now=now)
    assert len(df) == 119 and (df["biz_date"] == date(2026, 10, 26)).all()
    gc = df[(df["symbol"] == "GC") & (df["mmy"] == "202612")].iloc[0]
    assert (gc["uom_qty"], gc["settl_method"], gc["init_margin"], gc["maint_margin_field"]) == (100.0, "P", 20302.0, 1400.0)
    assert (gc["last_trd"], gc["first_notice"], gc["last_efp"]) == (date(2026, 12, 29), date(2026, 11, 30), date(2026, 12, 30))
    im = {(r.symbol, r.mmy): r.init_margin for r in df.itertuples(index=False)}
    assert im[("MGC", "202612")] == 2031.0 and im[("1OZ", "202612")] == 204.0 and im[("QO", "202612")] == 10152.0 and im[("SI", "202612")] == 22003.0
    res = ingest_cme.ingest_prf(store, read(G_CME / "cmeg.comex.fut.prf.csv.zip", binary=True), now=now, ref_prices={"GC": 4007.9})
    assert res["rows"] == 119 and res["margins"] == 119
    m = db.query_df(store, "SELECT margin_pct FROM gold_margins WHERE symbol = 'GC' AND expiry = DATE '2026-12-29'").iloc[0]
    assert m["margin_pct"] == pytest.approx(5.07, abs=0.01)                    # ≈5.1 % of notional (SOURCES C4)
