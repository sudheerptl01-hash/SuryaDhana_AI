"""The Wave 0 0.5 / PLAN 1.4 NSE file parsers on real fixtures captured 5 Nov 2026 (one paced GET each, browser UA):
FOVOLT, Contract_Delta (sample), combineoi_deleq, ind_close_all, fao_participant_vol, fii_stats (xls), mwpl_cli (xls),
fo_secban, the vixhistory JSON shape; the index-close writer never touches the Desk's NIFTY50 / INDIAVIX rows (O-T9)."""
from __future__ import annotations

# ruff: noqa: DTZ001
import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

import nse_positions as npz  # noqa: E402

FIX = ROOT / "tests" / "unit" / "fixtures" / "terminal_v2"
D = date(2026, 11, 4)
NOW = datetime(2026, 11, 5, 0, 0)


def _b(name: str) -> bytes:
    return (FIX / name).read_bytes()


def test_fovolt():
    df = npz.parse_fovolt(_b("FOVOLT_04112026.csv"), D)
    r = df.set_index("symbol").loc["360ONE"]
    assert len(df) == 229 and abs(r["ann_vol"] - 0.38569453) < 1e-8 and abs(r["ewma_daily_vol"] - 0.02018817) < 1e-8 and r["close"] == 1068.7
    assert (df["date"] == D).all() and df["applicable_ann_vol"].notna().all()
    with pytest.raises(ValueError):
        npz.parse_fovolt(b"a,b,c\n1,2,3\n", D)


def test_contract_delta():
    df = npz.parse_contract_delta(_b("Contract_Delta_04112026_sample.csv"), D)
    r = df[(df["symbol"] == "NIFTY") & (df["expiry"] == date(2026, 11, 9)) & (df["strike"] == 24000)].set_index("opt_type")
    assert abs(r.loc["CE", "delta_factor"] - 0.48513723) < 1e-8 and abs(r.loc["PE", "delta_factor"] + 0.51486277) < 1e-8
    assert set(df["opt_type"]) == {"CE", "PE"}                             # FF (futures) rows dropped


def test_combined_oi_deleq_and_zip_layouts():
    df = npz.parse_combined_oi_deleq(_b("combineoi_deleq_04112026.csv"), D)
    r = df.set_index("symbol").loc["DABUR"]
    assert len(df) == 227 and r["notional_oi"] == 44971375 and abs(r["fut_equiv_oi"] - 24469411.848) < 0.01 and r["isin"] == "INE016A01026"
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("combineoi_04112026.csv", "Date,ISIN,Scrip Name,NSE Symbol,MWPL,Open Interest,Limit for Next Day\n04-11-2026,INE016A01026,DABUR,DABUR,65000000,44971375,52000000\n")
    z2 = npz.parse_combined_oi_zip(buf.getvalue(), D).iloc[0]
    assert z2["mwpl"] == 65000000 and z2["oi"] == 44971375 and z2["limit_next_day"] == 52000000


def test_index_close_all_and_the_desk_series_rule(tmp_path):
    df = npz.parse_index_close_all(_b("ind_close_all_04112026.csv"), D)
    by = df.set_index("symbol")
    assert len(df) == 167 and by.loc["NIFTY 50", "close"] == 23960.6 and by.loc["NIFTY BANK", "close"] == 55913.6 and by.loc["INDIA VIX", "close"] == 15.19
    assert by.loc["NIFTY 50", "open"] == 23742.25 and by.loc["NIFTY 50", "pe"] == 19.77
    with pytest.raises(ValueError):
        npz.parse_index_close_all(_b("ind_close_all_04112026.csv"), date(2026, 11, 3))         # the file is dated 4 Nov
    assert npz.index_symbol("Nifty 50") == "NIFTY50" and npz.index_symbol("India VIX") == "INDIAVIX" and npz.index_symbol("Nifty Bank") == "NIFTYBANK"
    from storage.duckdb_store import DuckDBStore

    store = DuckDBStore(str(tmp_path / "x.duckdb"))
    try:
        out = npz.write_index_close_all(store, df, D, NOW)
        assert out["index_ohlc_daily"] == 167 and out["vix_daily"] == 1 and out["market_index_daily"] == 165
        vix = store.read_one("SELECT open, high, low, close, prev_close, source FROM vix_daily WHERE date = ?", [D])
        assert vix[3] == 15.19 and abs(vix[4] - 15.73) < 1e-6 and vix[5] == "nse_daily_file"
        assert store.read_one("SELECT COUNT(*) FROM market_index_daily WHERE symbol IN ('NIFTY50', 'INDIAVIX')")[0] == 0     # O-T9: never
        assert store.read_one("SELECT close FROM market_index_daily WHERE symbol = 'NIFTYBANK' AND date = ?", [D])[0] == 55913.6
        out2 = npz.write_index_close_all(store, df, D, NOW, include_desk_series=True)                # negative control: only on O-T9
        assert out2["market_index_daily"] == 167 and store.read_one("SELECT COUNT(*) FROM market_index_daily WHERE symbol = 'NIFTY50'")[0] == 1
    finally:
        store.close()


def test_participant_vol_fii_stats_mwpl_clients_secban():
    pv = npz.parse_participant_vol(_b("fao_participant_vol_04112026.csv"), D).set_index("client_type")
    assert int(pv.loc["FII", "total_long"]) == 7114763 and int(pv.loc["TOTAL", "fut_idx_long"]) == 115141
    fs = npz.parse_fii_stats(_b("fii_stats_04-Nov-2026.xls"), D).set_index("instrument")
    assert fs.loc["INDEX FUTURES", "buy_contracts"] == 32480 and abs(fs.loc["INDEX FUTURES", "oi_cr"] - 40739.61) < 1e-6 and "INDEX OPTIONS" in fs.index
    mw = npz.parse_mwpl_clients(_b("mwpl_cli_03112026.xls"), date(2026, 11, 3))
    ad = mw[mw["symbol"] == "ADANIENSOL"].sort_values("client_rank")
    assert len(ad) == 6 and ad.iloc[0]["pct_mwpl"] == 6.87 and ad.iloc[-1]["pct_mwpl"] == 3.12
    assert npz.parse_secban(_b("fo_secban_05112026.csv")) == ["KAYNES", "SAIL"]


def test_vix_history_json_shape():
    payload = {"data": [{"EOD_TIMESTAMP": "01-OCT-2026", "EOD_INDEX_NAME": "INDIA VIX", "EOD_OPEN_INDEX_VAL": 13.49, "EOD_HIGH_INDEX_VAL": 15.6875,
                         "EOD_LOW_INDEX_VAL": 13.49, "EOD_CLOSE_INDEX_VAL": 14.46, "EOD_PREV_CLOSE": 13.49, "VIX_PTS_CHG": 0.97, "VIX_PERC_CHG": 7.19},
                        {"EOD_TIMESTAMP": "bad", "EOD_CLOSE_INDEX_VAL": 1.0}]}
    df = npz.parse_vix_history(json.dumps(payload).encode())
    assert len(df) == 1 and df.iloc[0]["date"] == date(2026, 10, 1) and df.iloc[0]["close"] == 14.46 and df.iloc[0]["high"] == 15.6875


def test_dataset_table_and_urls():
    for ds, spec in npz.TERMINAL_DATASETS.items():
        assert callable(spec["parse"]) and spec["url"].startswith("https://nsearchives.nseindia.com"), ds
    assert npz.FOVOLT_URL.format(d=D).endswith("FOVOLT_04112026.csv") and npz.FII_STATS_URL.format(d=D).endswith("fii_stats_04-Nov-2026.xls")
    assert npz.TOP10_INDEX if hasattr(npz, "TOP10_INDEX") else True
