"""PRE page (services/data-service/preopen.py): NSE pre-open parsing, session timing, archive."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "data-service"))
import preopen as po  # noqa: E402

PAYLOAD = {
    "declines": 1, "unchanged": 0, "advances": 1, "timestamp": "09-Oct-2026 09:09:49", "totalTradedValue": 2.06e9,
    "data": [
        {"metadata": {"symbol": "APOLLOHOSP", "series": "EQ", "purpose": None, "lastPrice": 7950, "change": 284, "pChange": 3.7,
                      "previousClose": 7666, "finalQuantity": 8787, "totalTurnover": 69856650, "marketCap": 8.1e11,
                      "yearHigh": 9070.5, "yearLow": 6696.5, "iep": 7950},
         "detail": {"preOpenMarket": {"IEP": 7950, "totalBuyQuantity": 7893, "totalSellQuantity": 1089, "atoBuyQty": 0, "atoSellQty": 0}}},
        {"metadata": {"symbol": "XYZ", "series": "EQ", "lastPrice": 90, "change": -10, "pChange": -10, "previousClose": 100,
                      "finalQuantity": 0, "totalTurnover": 0, "yearHigh": None, "yearLow": None, "iep": 90},
         "detail": {"preOpenMarket": {"totalBuyQuantity": 0, "totalSellQuantity": 0}}},
        {"metadata": {}, "detail": {}},
    ],
}


def test_parse_flattens_and_computes_imbalance():
    out = po.parse(PAYLOAD)
    assert out["advances"] == 1 and out["timestamp"] == "09-Oct-2026 09:09:49"
    assert [r["symbol"] for r in out["rows"]] == ["APOLLOHOSP", "XYZ"]       # rows without a symbol dropped
    a = out["rows"][0]
    assert a["iep"] == 7950 and a["change_pct"] == 3.7 and a["prev_close"] == 7666
    assert a["imbalance"] == pytest.approx((7893 - 1089) / (7893 + 1089))
    assert a["vs_year_high_pct"] == pytest.approx((7950 / 9070.5 - 1) * 100)
    x = out["rows"][1]
    assert x["imbalance"] is None and x["vs_year_high_pct"] is None


def test_session_timing():
    assert po.session_date("09-Oct-2026 09:09:49") == "2026-10-09"
    assert po.session_date(None) is None
    assert po.is_final("09-Oct-2026 09:08:00") and not po.is_final("09-Oct-2026 09:05:12")
    assert po.PreOpenFeed._live_window(datetime(2026, 10, 12, 9, 3)) is True
    assert po.PreOpenFeed._live_window(datetime(2026, 10, 11, 9, 3)) is False   # Sunday
    assert po.PreOpenFeed._live_window(datetime(2026, 10, 12, 11, 0)) is False


def test_archive_writes_final_snapshot_once(tmp_path):
    feed = po.PreOpenFeed(tmp_path, {})
    feed._archive("FO", "09-Oct-2026 09:05:00", PAYLOAD)                   # not final yet
    assert not list(tmp_path.iterdir())
    feed._archive("FO", PAYLOAD["timestamp"], PAYLOAD)
    path = tmp_path / "2026-10-09_FO.json"
    assert json.loads(path.read_text())["advances"] == 1
    feed._archive("FO", PAYLOAD["timestamp"], {"data": [1]})               # already archived → unchanged
    assert json.loads(path.read_text())["advances"] == 1
