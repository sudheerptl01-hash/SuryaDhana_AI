"""Ownership shifts (DuckDBStore.holding_changes): latest shareholding filing vs the previous one, per stock."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "data-service"))
from storage import DuckDBStore  # noqa: E402


def test_latest_vs_previous_quarter(tmp_path):
    st = DuckDBStore(str(tmp_path / "t.duckdb"))
    base = {"public_pct": 40.0, "retail_holders": 1, "hni_holders": 1, "fpi_holders": 1, "mf_holders": 1, "xbrl_url": None, "broadcast_ts": "21-Jul-2026 10:00:00"}
    st.upsert_shareholding(pd.DataFrame([
        {**base, "symbol": "AAA", "period_end": "2026-03-31", "promoter_pct": 60.0, "fpi_pct": 10.0, "mf_pct": 8.0, "retail_pct": 15.0, "total_holders": 100000},
        {**base, "symbol": "AAA", "period_end": "2026-06-30", "promoter_pct": 59.5, "fpi_pct": 9.0, "mf_pct": 10.5, "retail_pct": 15.5, "total_holders": 120000},
        {**base, "symbol": "BBB", "period_end": "2026-06-30", "promoter_pct": 50.0, "fpi_pct": 5.0, "mf_pct": 5.0, "retail_pct": 30.0, "total_holders": 5000},
    ]))
    rows = {r["symbol"]: r for r in st.holding_changes()}
    a = rows["AAA"]
    assert a["period_end"] == "2026-06-30" and a["prev_period"] == "2026-03-31"
    assert a["d_mf"] == pytest.approx(2.5) and a["d_fpi"] == pytest.approx(-1.0) and a["d_promoter"] == pytest.approx(-0.5)
    assert a["d_holders_pct"] == pytest.approx(20.0)
    assert rows["BBB"]["d_mf"] is None and rows["BBB"]["prev_period"] is None
