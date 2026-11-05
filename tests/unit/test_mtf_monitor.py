"""MTF crowding monitor (DuckDBStore.mtf_monitor): funded amount, change over the lookback, days-to-unwind."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "data-service"))
from storage import DuckDBStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    st = DuckDBStore(str(tmp_path / "t.duckdb"))
    d1 = date.today() - timedelta(days=1)
    d0 = d1 - timedelta(days=28)
    with st._lock:
        for d, qa, qb in ((d0, 1000, 500), (d1, 1500, 500)):
            st._conn.execute("INSERT INTO nse_mtf VALUES (?, 'AAA', 'Aaa Ltd', ?, ?)", [d, qa, qa / 10])   # ₹ lakh
            st._conn.execute("INSERT INTO nse_mtf VALUES (?, 'BBB', 'Bbb Ltd', ?, ?)", [d, qb, 20.0])
            st._conn.execute("INSERT INTO nse_mtf_market VALUES (?, 100, 10, 5, 105)", [d])
        for i in range(20):
            st._conn.execute("INSERT INTO nse_bhavcopy (symbol, series, date, close, turnover_lacs) VALUES ('AAA', 'EQ', ?, 50, 30)",
                             [d1 - timedelta(days=i)])
    return st


def test_mtf_monitor_change_and_days_to_unwind(store):
    out = store.mtf_monitor(lookback=20)
    rows = {r["symbol"]: r for r in out["stocks"]}
    assert out["base_date"] < out["as_of"] and len(out["market"]) == 2
    assert rows["AAA"]["amount_cr"] == pytest.approx(1.5)                 # 150 lakh
    assert rows["AAA"]["qty_chg_pct"] == pytest.approx(50.0)
    assert rows["AAA"]["days_to_unwind"] == pytest.approx(5.0)            # 150 lakh ÷ 30 lakh a day
    assert rows["BBB"]["qty_chg_pct"] == pytest.approx(0.0) and rows["BBB"]["days_to_unwind"] is None
    assert [r["symbol"] for r in out["stocks"]] == ["AAA", "BBB"]          # largest funded amount first
