"""DEAL page (services/data-service/deals_monitor.py): netting, institution tag, share of volume, move since."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))
import deals_monitor as dm  # noqa: E402


def _deals() -> pd.DataFrame:
    return pd.DataFrame([
        # a mutual fund buys 100k @ 500 (₹5 cr)
        {"date": "2026-10-05", "kind": "bulk", "symbol": "ABC", "security_name": "Abc Ltd", "client_name": "XYZ MUTUAL FUND", "side": "BUY", "qty": 100_000, "price": 500.0},
        # an intraday round trip: bought and sold the same → drops out
        {"date": "2026-10-05", "kind": "bulk", "symbol": "ABC", "security_name": "Abc Ltd", "client_name": "HFT LLP", "side": "BUY", "qty": 50_000, "price": 500.0},
        {"date": "2026-10-05", "kind": "bulk", "symbol": "ABC", "security_name": "Abc Ltd", "client_name": "HFT LLP", "side": "SELL", "qty": 50_000, "price": 501.0},
        # a promoter entity sells 40k @ 100 in a block (₹40 lakh)
        {"date": "2026-10-06", "kind": "block", "symbol": "DEF", "security_name": "Def Ltd", "client_name": "PROMOTER HOLDCO", "side": "SELL", "qty": 40_000, "price": 100.0},
    ])


def _px() -> pd.DataFrame:
    return pd.DataFrame([
        {"symbol": "ABC", "date": "2026-10-05", "close": 500.0, "volume": 1_000_000},
        {"symbol": "ABC", "date": "2026-10-09", "close": 550.0, "volume": 400_000},
        {"symbol": "DEF", "date": "2026-10-06", "close": 100.0, "volume": 80_000},
        {"symbol": "DEF", "date": "2026-10-09", "close": 90.0, "volume": 50_000},
    ])


def test_round_trips_drop_out_and_institution_is_tagged():
    rows = dm.build_deals(_deals(), _px())
    assert [(r["symbol"], r["client_name"]) for r in rows] == [("DEF", "PROMOTER HOLDCO"), ("ABC", "XYZ MUTUAL FUND")]
    abc = rows[1]
    assert abc["direction"] == "buy" and abc["institution"] is True
    assert abc["value"] == pytest.approx(5e7)
    assert abc["pct_of_volume"] == pytest.approx(10.0)
    assert abc["since_pct"] == pytest.approx(10.0)
    defr = rows[0]
    assert defr["direction"] == "sell" and defr["institution"] is False
    assert defr["pct_of_volume"] == pytest.approx(50.0)
    assert defr["since_pct"] == pytest.approx(-10.0)


def test_min_value_and_summary():
    rows = dm.build_deals(_deals(), _px(), min_value=1e7)
    assert [r["symbol"] for r in rows] == ["ABC"]
    s = dm.summarize(dm.build_deals(_deals(), _px()))
    assert s["deals"] == 2 and s["buy_value"] == pytest.approx(5e7) and s["sell_value"] == pytest.approx(4e6)
    assert s["institution_value"] == pytest.approx(5e7)
    assert [t["symbol"] for t in s["top_net"]][:1] == ["ABC"] and s["top_net"][-1]["symbol"] == "DEF"


def test_empty_inputs():
    assert dm.build_deals(pd.DataFrame(), pd.DataFrame()) == []
    assert dm.summarize([])["deals"] == 0
    rows = dm.build_deals(_deals(), pd.DataFrame())
    assert rows and rows[0]["since_pct"] is None


def test_block_reported_again_in_bulk_file_counts_once():
    trade = {"date": "2026-10-12", "symbol": "JUBLPHARMA", "security_name": "Jubilant", "client_name": "QUANT MUTUAL FUND",
             "side": "SELL", "qty": 1_100_000, "price": 915.0}
    deals = pd.DataFrame([{**trade, "kind": "block"}, {**trade, "kind": "bulk"}])
    rows = dm.build_deals(deals, pd.DataFrame())
    assert len(rows) == 1 and rows[0]["kind"] == "block"


def test_short_selling_ranks_by_share_of_volume():
    import pandas as pd
    shorts = pd.DataFrame({"date": pd.to_datetime(["2026-10-12", "2026-10-13", "2026-10-13"]),
                           "symbol": ["AAA", "AAA", "BBB"], "qty": [1000.0, 500.0, 50_000.0]})
    vol = pd.DataFrame({"date": pd.to_datetime(["2026-10-12", "2026-10-13", "2026-10-13", "2026-10-12"]),
                        "symbol": ["AAA", "AAA", "BBB", "BBB"], "volume": [10_000.0, 5_000.0, 5_000_000.0, 5_000_000.0]})
    rows = dm.short_selling(shorts, vol)
    assert [r["symbol"] for r in rows] == ["AAA", "BBB"]           # 10% of volume beats 0.5%, despite fewer shares
    a = rows[0]
    assert a["short_qty"] == 1500 and a["days"] == 2 and a["last"] == "2026-10-13" and a["short_pct_of_volume"] == 10.0
    assert dm.short_selling(shorts.iloc[0:0], vol) == []
