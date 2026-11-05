"""NSE bhavcopy ingestion: parsing, caching, holiday handling, DuckDB upsert (offline)."""
import sys
from datetime import date
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "services/data-service"))

import bhavcopy  # noqa: E402
from storage.duckdb_store import DuckDBStore  # noqa: E402

CSV = """SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
20MICRONS, EQ, 25-Sep-2026, 213.87, 215.01, 219.80, 212.78, 217.55, 217.58, 216.90, 101345, 219.81, 2985, 35886, 35.41
GOLDBEES, EQ, 25-Sep-2026, 60.10, 60.00, 60.50, 59.90, 60.20, 60.25, 60.21, 500000, 301.05, 1200, -, -
M&M, EQ, 25-Sep-2026, 3000.00, 2990.00, 3010.00, 2950.00, 2980.00, 2982.70, 2975.00, 900000, 26775.00, 50000, 450000, 50.00
"""


def test_parse_strips_spaces_and_handles_missing_delivery():
    df = bhavcopy.parse_bhavcopy(CSV)
    assert list(df["symbol"]) == ["20MICRONS", "GOLDBEES", "M&M"]
    row = df.iloc[0]
    assert row["series"] == "EQ" and row["date"] == date(2026, 9, 25)
    assert row["close"] == 217.58 and row["deliv_pct"] == 35.41 and row["volume"] == 101345
    assert df.iloc[1][["deliv_qty", "deliv_pct"]].isna().all()


def _client(calls: list) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if "25092026" in str(req.url):
            return httpx.Response(200, text=CSV)
        if "24092026" in str(req.url):
            return httpx.Response(404)                        # holiday
        return httpx.Response(200, text="<html>blocked</html>")   # not a CSV → retried then error
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ingest_range_caches_counts_holidays_and_upserts(tmp_path, monkeypatch):
    monkeypatch.setattr(bhavcopy.time, "sleep", lambda s: None)
    store = DuckDBStore(str(tmp_path / "m.duckdb"))
    calls: list = []
    res = bhavcopy.ingest_range(store, date(2026, 9, 23), date(2026, 9, 27), tmp_path / "cache",
                                client=_client(calls))
    assert res["days_requested"] == 5                     # 23–27 Sep incl. the weekend (special sessions exist)
    # 24th = 404 holiday; 23rd/26th/27th = non-CSV → retried then failure
    assert res["days_loaded"] == 1 and res["days_missing"] == 1 and res["failure_count"] == 3
    assert res["rows_written"] == 3
    assert bhavcopy.cache_path(tmp_path / "cache", date(2026, 9, 25)).exists()
    meta = store.get_bhavcopy_meta()
    assert meta["rows"] == 3 and meta["last_date"] == "2026-09-25"

    calls.clear()                                          # second run: served from cache, no request
    res2 = bhavcopy.ingest_range(store, date(2026, 9, 25), date(2026, 9, 25), tmp_path / "cache",
                                 client=_client(calls))
    wk = bhavcopy.ingest_range(store, date(2026, 9, 21), date(2026, 9, 27), tmp_path / "cache",
                               client=_client([]), days_filter="weekends")
    assert wk["days_requested"] == 2
    assert res2["days_cached"] == 1 and calls == []
    assert store.get_bhavcopy_meta()["rows"] == 3          # upsert, not duplicate
    store.close()


def test_xlsx_served_under_csv_name_is_converted(tmp_path):
    import io as _io
    import pandas as pd
    buf = _io.BytesIO()
    pd.read_csv(_io.StringIO(CSV), skipinitialspace=True).to_excel(buf, index=False)
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=buf.getvalue())))
    text, status = bhavcopy.download_day(date(2022, 8, 8), tmp_path, client)
    assert status == "downloaded"
    df = bhavcopy.parse_bhavcopy(text)
    assert len(df) == 3 and df.iloc[0]["symbol"] == "20MICRONS"


OLD = """SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,
20MICRONS,EQ,30.45,31,30.25,30.4,30.4,30.6,37604,1150220.95,01-JAN-2015,200,INE144J01027,
INFY,EQ,1980,2000,1975,1990,1991,1970,100000,199000000,01-JAN-2015,5000,INE009A01021,
"""


def test_old_cm_bhavcopy_zip_is_converted_to_full_layout(tmp_path):
    import io as _io
    import zipfile
    assert "EQUITIES/2015/JAN/cm01JAN2015bhav.csv.zip" in bhavcopy.url_for(date(2015, 1, 1))
    assert "sec_bhavdata_full_01102019" in bhavcopy.url_for(date(2019, 10, 1))
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("cm01JAN2015bhav.csv", OLD)
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=buf.getvalue())))
    text, status = bhavcopy.download_day(date(2015, 1, 1), tmp_path, client)
    assert status == "downloaded"
    df = bhavcopy.parse_bhavcopy(text)
    infy = df[df["symbol"] == "INFY"].iloc[0]
    assert infy["date"] == date(2015, 1, 1) and infy["prev_close"] == 1970 and infy["close"] == 1990
    assert infy["avg_price"] == 1990.0 and infy["turnover_lacs"] == 1990.0 and infy["trades"] == 5000
    assert df["deliv_pct"].isna().all()


def test_file_for_another_session_is_dropped_and_its_cache_purged(tmp_path, monkeypatch):
    """19 Oct 2026: NSE answered the Sunday (18 Oct) URL with Friday's rows. Cached under the
    requested date, such a file would short-circuit every later run and the real session's file
    would never be fetched (a silent, permanent data hole on a publication-delay day)."""
    monkeypatch.setattr(bhavcopy.time, "sleep", lambda s: None)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CSV)                       # every date gets the 25-Sep file
    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = DuckDBStore(str(tmp_path / "m.duckdb"))
    res = bhavcopy.ingest_range(store, date(2026, 9, 25), date(2026, 9, 27), tmp_path / "cache", client=client)
    assert res["days_loaded"] == 1 and res["days_missing"] == 2       # 26th + 27th carried 25-Sep rows
    assert [m["requested"] for m in res["date_mismatches"]] == ["2026-09-26", "2026-09-27"]
    assert not bhavcopy.cache_path(tmp_path / "cache", date(2026, 9, 26)).exists()   # never poisons a rerun
    assert bhavcopy.cache_path(tmp_path / "cache", date(2026, 9, 25)).exists()
    assert store.get_bhavcopy_meta()["last_date"] == "2026-09-25"
    store.close()


def test_poisoned_cache_from_before_the_fix_self_heals(tmp_path):
    """An already-cached mismatched file (like data/nse_bhavcopy/2026/…20261018) is purged on the next run."""
    cache = tmp_path / "cache"
    p = bhavcopy.cache_path(cache, date(2026, 9, 27))
    p.parent.mkdir(parents=True, exist_ok=True)
    import gzip
    p.write_bytes(gzip.compress(CSV.encode()))                       # 25-Sep rows under a 27-Sep name
    store = DuckDBStore(str(tmp_path / "m.duckdb"))
    res = bhavcopy.ingest_range(store, date(2026, 9, 27), date(2026, 9, 27), cache,
                                client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    assert res["days_loaded"] == 0 and res["date_mismatches"][0]["requested"] == "2026-09-27"
    assert not p.exists()
    store.close()
