"""NSE "who is holding overnight" ingestion: parsers for every format + DuckDB round trips (offline)."""
import io
import sys
import zipfile
from datetime import date
from pathlib import Path

import httpx
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "services/data-service"))

import nse_filings  # noqa: E402
import nse_positions as npos  # noqa: E402
from storage.duckdb_store import DuckDBStore  # noqa: E402

DAY = date(2023, 9, 21)

OLD_FO = """INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP,
FUTSTK,INFY,28-Sep-2023,0,XX,1488.3,1499.6,1476.3,1497.85,1497.85,19648,117087.37,20142800,188000,21-SEP-2023,
FUTSTK,INFY,26-Oct-2023,0,XX,1493.5,1497.5,1475.45,1496.1,1496.1,4966,29584.43,2942400,537200,21-SEP-2023,
OPTSTK,INFY,28-Sep-2023,1500,CE,10,12,8,11,11,500,300.5,1000000,50000,21-SEP-2023,
OPTSTK,INFY,28-Sep-2023,1480,PE,6,7,5,6,6,300,120.0,400000,-20000,21-SEP-2023,
FUTIDX,NIFTY,28-Sep-2023,0,XX,19900,19950,19800,19910,19910,100000,999999,12000000,-5000,21-SEP-2023,
"""

UDIFF_FO = """TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4
2026-09-25,2026-09-25,FO,NSE,STF,1,,INFY,,2026-09-29,2026-09-29,,,INFY26SEPFUT,1010,1015,999,1001.4,1001.5,1012,1000.2,1001.4,39331200,-14269200,56631,22687190000,43587,F1,400,,,,,
2026-09-25,2026-09-25,FO,NSE,STF,2,,INFY,,2026-10-27,2026-10-27,,,INFY26OCTFUT,1012,1018,1003,1005.8,1005.9,1015,1000.2,1005.8,41268800,17137200,53949,21698070000,39538,F1,400,,,,,
2026-09-25,2026-09-25,FO,NSE,STO,3,,INFY,,2026-10-27,2026-10-27,1000,CE,INFY26OCT1000CE,40,45,35,37,37,42,1000.2,37,2252400,506400,4316,172640000,900,F1,400,,,,,
"""

PARTICIPANT = """"Participant wise Open Interest (no. of contracts) in Equity Derivatives as on Sep 25, 2026"
Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short\t,Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short,Option Stock Call Long,Option Stock Put Long,Option Stock Call Short,Option Stock Put Short,Total Long Contracts\t,Total Short Contracts
Client,310325,65926,3545318,250634,3903133,2935201,3250000,2400000,900000,700000,800000,650000,12294000,7416560
FII,46305,358306,3498393,3003382,857125,1401782,1000000,900000,300000,200000,250000,210000,6303605,5721688
TOTAL,488031,488031,8378323,8378323,6069693,5705755,6069693,5705755,1300000,1100000,1300000,1100000,24000000,24000000
"""

BULK = """Date ,Symbol ,Security Name ,Client Name ,Buy / Sell ,Quantity Traded ,Trade Price / Wght. Avg. Price ,Remarks
25-SEP-2026,ABC,ABC Ltd,SBI MUTUAL FUND,BUY,"1,20,000",512.35,-
25-SEP-2026,ABC,ABC Ltd,SOME TRADER,SELL,50000,515.00,-
"""
SHORT = """Date ,Symbol ,Security Name ,Quantity
01-SEP-2026,ADANIENT,ADANI ENTERPRISES LIMITED,12
"""

MTF = """SEBI REPORT AS ON Reporting date 24-SEP-2026,,,
,Sr.No.,Particulars,Rs. In Lakhs
,1,Scripwise Total Outstanding on the beginning of the day,14907073.90
,2,Fresh Exposure taken during the day,440893.45
,3,Exposure liquidated during the day,335161.72
,4,Net scripwise outstanding at the end of the day,15012805.63
Symbol,Name,Qty Fin by all the members(No.of Shares),Amt Fin by all the members(Rs. In Lakhs)
INFY,INFOSYS LIMITED,1234567,12345.67
TCS,TATA CONSULTANCY SERV LT,200000,6400.00
"""


def _zip(text: str, name: str = "x.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


def test_old_fo_format_aggregates_per_underlying():
    agg = npos.aggregate_fo(npos.parse_fo_bhavcopy(_zip(OLD_FO), DAY)).set_index("symbol")
    infy = agg.loc["INFY"]
    assert infy["kind"] == "stock" and str(infy["near_expiry"]) == "2023-09-28"
    assert infy["fut_close"] == 1497.85                       # nearest expiry's price
    assert infy["fut_oi"] == 20142800 + 2942400               # summed across expiries (shares)
    assert infy["fut_oi_chg"] == 188000 + 537200
    assert infy["call_oi"] == 1000000 and infy["put_oi"] == 400000 and infy["put_oi_chg"] == -20000
    assert agg.loc["NIFTY", "kind"] == "index"


def test_udiff_fo_format_converts_value_to_lakh():
    rows = npos.parse_fo_bhavcopy(_zip(UDIFF_FO), date(2026, 9, 25))
    fut = rows[rows["instrument"] == "FUT"].sort_values("expiry")
    assert fut["oi"].tolist() == [39331200, 41268800]
    assert abs(fut["value_lakh"].iloc[0] - 226871.9) < 0.01    # ₹ 22,687,190,000 → ₹ lakh
    agg = npos.aggregate_fo(rows).iloc[0]
    assert agg["fut_contracts"] == 56631 + 53949 and agg["call_oi"] == 2252400 and agg["put_oi"] == 0


def test_fo_urls_switch_format_on_8_jul_2024():
    assert "historical/DERIVATIVES" in npos.fo_urls(date(2024, 7, 5))[0]
    assert "BhavCopy_NSE_FO" in npos.fo_urls(date(2024, 7, 8))[0]


def test_participant_oi_skips_title_and_tabs():
    df = npos.parse_participant_oi(PARTICIPANT.encode(), date(2026, 9, 25)).set_index("client_type")
    assert list(df.index) == ["CLIENT", "FII", "TOTAL"]
    assert df.loc["FII", "fut_idx_short"] == 358306 and df.loc["CLIENT", "total_short"] == 7416560


def test_deals_parse_padded_headers_indian_commas_and_short_side():
    bulk = npos.parse_deals(BULK.encode(), "bulk")
    assert bulk["qty"].tolist() == [120000, 50000] and bulk["side"].tolist() == ["BUY", "SELL"]
    assert str(bulk["date"].iloc[0]) == "2026-09-25" and bulk["remarks"].isna().all()
    short = npos.parse_deals(SHORT.encode(), "short")
    assert short.iloc[0]["side"] == "SELL" and short.iloc[0]["qty"] == 12


def test_mtf_report_totals_and_table():
    table, totals = npos.parse_mtf(_zip(MTF), date(2026, 9, 24))
    assert totals["end_lakh"] == 15012805.63 and totals["fresh_lakh"] == 440893.45
    assert table.set_index("symbol").loc["INFY", "qty_financed"] == 1234567


class _Archive:
    """Serves one F&O zip; everything else 404 (weekends, holidays)."""
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if request.url.path.endswith("fo21SEP2023bhav.csv.zip"):
            return httpx.Response(200, content=_zip(OLD_FO))
        return httpx.Response(404)


def test_ingest_daily_caches_and_skips_missing_days(tmp_path):
    store = DuckDBStore(str(tmp_path / "m.duckdb"))
    server = _Archive()
    client = httpx.Client(transport=httpx.MockTransport(server))
    first = npos.ingest_daily(store, "fo", DAY, date(2023, 9, 23), tmp_path / "cache", client=client, sleep_s=0)
    assert first["loaded"] == 1 and first["missing"] == 2 and first["rows_written"] == 2
    calls = server.calls
    again = npos.ingest_daily(store, "fo", DAY, DAY, tmp_path / "cache", client=client, sleep_s=0)
    assert again["cached"] == 1 and server.calls == calls        # served from the on-disk cache
    assert store.last_date("nse_fo_daily") == "2023-09-21"


def test_replace_deals_is_idempotent(tmp_path):
    store = DuckDBStore(str(tmp_path / "m.duckdb"))
    df = npos.parse_deals(BULK.encode(), "bulk")
    for _ in range(2):
        store.replace_deals("bulk", date(2026, 9, 1), date(2026, 9, 30), df)
    assert store.get_positions_meta()["nse_deals"]["rows"] == 2


def test_insider_mapping_uses_intimation_date():
    rec = {"did": "1", "pid": "2", "acqName": "Promoter X", "personCategory": "Promoter Group", "acqMode": "Market Purchase",
           "tdpTransactionType": "Buy", "secAcq": "10,000", "secVal": "5000000", "befAcqSharesPer": "40.1",
           "afterAcqSharesPer": "40.2", "acqfromDt": "20-Sep-2026", "acqtoDt": "21-Sep-2026", "intimDt": "23-Sep-2026",
           "date": "23-Sep-2026 18:05"}
    row = nse_filings.parse_insider([rec], "ABC").iloc[0]
    assert row["qty"] == 10000 and row["intimation_date"] == "2026-09-23" and row["mode"] == "Market Purchase"


def _xbrl(retail_pct: str, fpi_pct: str) -> str:
    tag = lambda name, ctx, v: f'<in-bse-shp:{name} contextRef="{ctx}" unitRef="U">{v}</in-bse-shp:{name}>'  # noqa: E731
    return "".join([
        tag("NumberOfShareholders", "ShareholdingPattern_ContextI", "2958297"),
        tag("NumberOfShareholders", "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh_ContextI", "2847017"),
        tag("NumberOfShareholders", "ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh_ContextI", "1147"),
        tag("NumberOfShareholders", "InstitutionsForeignPortfolioInvestorCategoryOne_ContextI", "1288"),
        tag("NumberOfShareholders", "InstitutionsForeignPortfolioInvestorCategoryTwo_ContextI", "89"),
        tag("NumberOfShareholders", "DetailsOfSharesHeldByInstitutionsForeignPortfolioInvestorOne_Context15", "1"),
        tag("NumberOfShareholders", "MutualFundsOrUTI_ContextI", "45"),
        tag("ShareholdingAsAPercentageOfTotalNumberOfShares", "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh_ContextI", retail_pct),
        tag("ShareholdingAsAPercentageOfTotalNumberOfShares", "InstitutionsForeignPortfolioInvestorCategoryOne_ContextI", fpi_pct),
        tag("ShareholdingAsAPercentageOfTotalNumberOfShares", "ShareholdingOfPromoterAndPromoterGroup_ContextI", "0.1382" if float(fpi_pct) < 1 else "13.82"),
    ])


def test_shareholding_xbrl_counts_and_fraction_scaling():
    new = nse_filings.parse_shareholding_xbrl(_xbrl("0.0745", "0.27"))      # newer filings: fractions
    old = nse_filings.parse_shareholding_xbrl(_xbrl("7.45", "27.0"))        # older filings: percent
    assert new["total_holders"] == 2958297 and new["retail_holders"] == 2847017 and new["hni_holders"] == 1147
    assert new["fpi_holders"] == 1288 + 89 and new["mf_holders"] == 45       # detail rows not double counted
    assert round(new["retail_pct"], 2) == round(old["retail_pct"], 2) == 7.45
    assert round(new["fpi_pct"], 2) == round(old["fpi_pct"], 2) == 27.0


def _old_xbrl(fpi_contexts: dict[str, str]) -> str:
    """Pre-2025 layout: contexts end in a bare `I`, `MutualFundsOrUti`, percent values."""
    tag = lambda name, ctx, v: f'<in-bse-shp:{name} contextRef="{ctx}" unitRef="U">{v}</in-bse-shp:{name}>'  # noqa: E731
    parts = [
        tag("NumberOfShareholders", "ShareholdingPatternI", "29117"),
        tag("NumberOfShareholders", "IndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakhI", "26787"),
        tag("NumberOfShareholders", "IndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakhI", "12"),
        tag("NumberOfShareholders", "MutualFundsOrUtiI", "14"),
        tag("ShareholdingAsAPercentageOfTotalNumberOfShares", "IndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakhI", "6.28"),
        tag("ShareholdingAsAPercentageOfTotalNumberOfShares", "MutualFundsOrUtiI", "1.2"),
        tag("ShareholdingAsAPercentageOfTotalNumberOfShares", "ForeignPortfolioInvestorI", "0"),     # promoter-side FPI
        tag("ShareholdingAsAPercentageOfTotalNumberOfShares", "ShareholdingPatternI", "100"),
        tag("NumberOfShareholders", "DetailsOfSharesHeldByInstitutionsForeignPortfolioInvestorOne001I", "1"),
    ]
    for ctx, pct in fpi_contexts.items():
        parts += [tag("NumberOfShareholders", ctx, "80"),
                  tag("ShareholdingAsAPercentageOfTotalNumberOfShares", ctx, pct)]
    return "".join(parts)


def test_older_xbrl_layouts_map_to_the_same_categories():
    # 2022-24: FPI Category I/II with NSE's own "Catergory" spelling; 2019-21: one FPI line.
    split = nse_filings.parse_shareholding_xbrl(_old_xbrl({
        "InstitutionsForeignPortfolioInvestorCatergoryOneI": "31.48",
        "InstitutionsForeignPortfolioInvestorCatergoryTwoI": "0"}))
    single = nse_filings.parse_shareholding_xbrl(_old_xbrl({"InstitutionsForeignPortfolioInvestorI": "22.69"}))
    assert split["fpi_pct"] == 31.48 and split["fpi_holders"] == 160
    assert single["fpi_pct"] == 22.69 and single["fpi_holders"] == 80
    for row in (split, single):
        assert row["total_holders"] == 29117 and row["retail_holders"] == 26787 and row["hni_holders"] == 12
        assert row["retail_pct"] == 6.28 and row["mf_pct"] == 1.2 and row["mf_holders"] == 14


class _XbrlHost:
    def __init__(self, xml: str):
        self.xml, self.calls = xml, 0

    def __call__(self, request):
        self.calls += 1
        return httpx.Response(200, text=self.xml)


def test_reparse_fills_missing_categories_from_cached_xbrl(tmp_path):
    store = DuckDBStore(str(tmp_path / "m.duckdb"))
    url = "https://nsearchives.nseindia.com/corporate/xbrl/SHP_1_2_WEB.xml"
    store.upsert_shareholding(pd.DataFrame([{
        "symbol": "ABC", "period_end": "2022-12-31", "broadcast_ts": "17-JAN-2023 17:42:24", "promoter_pct": 22.03,
        "public_pct": 77.97, "xbrl_url": url, **dict.fromkeys(nse_filings._COUNT_FIELDS)}]))
    archive = _XbrlHost(_old_xbrl({"InstitutionsForeignPortfolioInvestorCatergoryOneI": "31.48"}))
    client = httpx.Client(transport=httpx.MockTransport(archive))
    out = nse_filings.reparse_shareholding(store, client, tmp_path / "xbrl")
    assert out == {"reparse_candidates": 1, "reparsed": 1, "failures": [], "failure_count": 0}
    assert store.shareholding_missing_categories() == []
    row = store._conn.execute("SELECT fpi_pct, mf_pct, promoter_pct FROM nse_shareholding").fetchone()
    assert row == (31.48, 1.2, 22.03)                       # filing-level fields kept
    assert (tmp_path / "xbrl" / "SHP_1_2_WEB.xml.gz").exists() and archive.calls == 1
    nse_filings.fetch_xbrl(client, url, tmp_path / "xbrl")
    assert archive.calls == 1                               # replays come from the cache


def test_filings_without_xbrl_are_not_fetched(tmp_path):
    store = DuckDBStore(str(tmp_path / "m.duckdb"))
    store.upsert_shareholding(pd.DataFrame([{
        "symbol": "ABB", "period_end": "2022-03-31", "broadcast_ts": "21-APR-2022 17:00:00", "promoter_pct": 75.0,
        "public_pct": 25.0, "xbrl_url": "https://nsearchives.nseindia.com/corporate/xbrl/-",   # NSE's "none"
        **dict.fromkeys(nse_filings._COUNT_FIELDS)}]))
    assert store.shareholding_missing_categories() == []


def test_insider_feed_duplicates_are_collapsed(tmp_path):
    rec = {"did": "9", "pid": "8", "acqName": "Director Y", "acqfromDt": "14-Feb-2024", "secAcq": "100",
           "intimDt": "16-Feb-2024", "acqMode": "Market Sale", "tdpTransactionType": "Sell"}
    df = nse_filings.parse_insider([rec, dict(rec)], "BIOCON")
    assert len(df) == 1
    store = DuckDBStore(str(tmp_path / "m.duckdb"))
    assert store.upsert_insider_trades(df) == 1


def test_insider_windows_always_carry_a_date_range():
    # Without dates the API returns only the newest 20 records per company.
    assert nse_filings.insider_windows(None, today=date(2026, 9, 28)) == [(date(2026, 8, 14), date(2026, 9, 28))]
    assert nse_filings.insider_windows(date(2019, 1, 1), today=date(2026, 9, 28)) == [(date(2019, 1, 1), date(2026, 9, 28))]
    years = nse_filings.yearly_windows(date(2024, 3, 1), date(2026, 9, 28))
    assert years[0] == (date(2024, 3, 1), date(2024, 12, 31)) and years[-1] == (date(2026, 1, 1), date(2026, 9, 28))


class _ShpFeed:
    """Shareholding master that repeats one filing (as PHOENIXLTD's feed did)."""
    def __call__(self, request):
        if "corporates-pit" in request.url.path:
            return httpx.Response(200, json={"data": []})
        if "share-holdings-master" in request.url.path:
            f = {"date": "30-SEP-2022", "broadcastDate": "20-OCT-2022 18:10:49", "pr_and_prgrp": "47.3",
                 "public_val": "52.7", "xbrl": None}
            return httpx.Response(200, json=[f, dict(f)])
        return httpx.Response(404)


def test_duplicate_shareholding_filings_in_one_feed_are_stored_once(tmp_path):
    store = DuckDBStore(str(tmp_path / "m.duckdb"))
    client = httpx.Client(transport=httpx.MockTransport(_ShpFeed()))
    out = nse_filings.ingest_filings(store, ["PHOENIXLTD"], client=client, sleep_s=0, xbrl_per_symbol=5)
    assert out["failure_count"] == 0 and out["shareholding_rows"] == 1
