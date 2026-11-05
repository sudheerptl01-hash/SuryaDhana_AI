"""Insider monitor query (DuckDBStore.insider_buys): the H4 definition — market purchases by promoters / directors /
KMP of at least ₹10 lakh — aggregated per stock, with the move since the latest filing."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "data-service"))
from storage import DuckDBStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    st = DuckDBStore(str(tmp_path / "t.duckdb"))
    d0 = date.today() - timedelta(days=10)
    trades = pd.DataFrame([
        # counts: promoter market purchase ≥ ₹10 L
        {"record_id": "a", "symbol": "AAA", "person": "P1", "category": "Promoter", "mode": "Market Purchase", "txn_type": "Buy",
         "qty": 1000, "value": 2e6, "intimation_date": d0},
        {"record_id": "b", "symbol": "AAA", "person": "P2", "category": "Director", "mode": "Market Purchase", "txn_type": "Buy",
         "qty": 1000, "value": 3e6, "intimation_date": d0 + timedelta(days=2)},
        # excluded: too small, ESOP, sale, employee
        {"record_id": "c", "symbol": "BBB", "person": "P3", "category": "Promoter", "mode": "Market Purchase", "txn_type": "Buy",
         "qty": 10, "value": 5e5, "intimation_date": d0},
        {"record_id": "d", "symbol": "CCC", "person": "P4", "category": "KMP", "mode": "ESOP", "txn_type": "Buy",
         "qty": 10, "value": 5e6, "intimation_date": d0},
        {"record_id": "e", "symbol": "DDD", "person": "P5", "category": "Promoter", "mode": "Market Sale", "txn_type": "Sell",
         "qty": 10, "value": 5e6, "intimation_date": d0},
        {"record_id": "f", "symbol": "EEE", "person": "P6", "category": "Designated Person", "mode": "Market Purchase", "txn_type": "Buy",
         "qty": 10, "value": 5e6, "intimation_date": d0},
    ])
    for c in ("before_pct", "after_pct", "from_date", "to_date", "broadcast_ts"):
        trades[c] = None
    st.upsert_insider_trades(trades)
    with st._lock:
        for i in range(12):
            st._conn.execute("INSERT INTO nse_bhavcopy (symbol, series, date, close) VALUES ('AAA', 'EQ', ?, ?)",
                             [d0 + timedelta(days=i), 100.0 if i <= 2 else 110.0])
    return st


def test_insider_buys_h4_definition(store):
    rows = store.insider_buys(days=60, min_value=1e6)
    assert [r["symbol"] for r in rows] == ["AAA"]
    r = rows[0]
    assert r["trades"] == 2 and r["buyers"] == 2 and r["total_value"] == 5e6
    assert r["filing_close"] == 100.0 and r["last_close"] == 110.0 and r["since_filing_pct"] == pytest.approx(10.0)
