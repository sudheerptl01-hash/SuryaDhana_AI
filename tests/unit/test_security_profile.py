"""Stock profile blocks (services/data-service/security.py) on synthetic NSE rows."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "data-service"))
import security as sec  # noqa: E402


def _bars(n: int = 300, start: float = 100.0, drift: float = 0.001) -> pd.DataFrame:
    dates = pd.bdate_range("2025-06-02", periods=n)
    close = start * np.exp(np.arange(n) * drift)
    return pd.DataFrame({
        "date": dates, "series": "EQ", "close": close, "adj_close": close, "adj_open": close, "adj_high": close * 1.01,
        "adj_low": close * 0.99, "adj_volume": 1e6, "adj_factor": 1.0, "turnover_lacs": 500.0, "deliv_pct": 50.0,
    })


def test_price_block_returns_range_and_trend():
    p = sec.price_block(_bars())
    assert p["returns"]["1M"] == pytest.approx((np.exp(21 * 0.001) - 1) * 100, abs=0.01)
    assert p["above"] == {"sma20": True, "sma50": True, "sma200": True}       # steady uptrend
    assert p["from_high_pct"] < 0 < p["from_low_pct"]
    assert p["turnover_cr"] == 5.0 and p["volume_x50"] == 1.0
    assert p["returns"]["1Y"] is not None


def test_price_block_short_history_has_no_long_returns():
    p = sec.price_block(_bars(n=30))
    assert p["returns"]["3M"] is None and p["returns"]["1Y"] is None
    assert p["above"]["sma200"] is None


def test_insider_net_counts_only_on_market_trades():
    ins = pd.DataFrame({
        "intimation_date": pd.to_datetime(["2026-09-01", "2026-08-01", "2026-07-01", "2026-06-01"]),
        "person": ["A", "B", "C", "D"], "category": "Promoter",
        "txn_type": ["Buy", "Sell", "Buy", "Buy"],
        "mode": ["Market Purchase", "Market Sale", "Off Market", "Revokation of Pledge"],
        "qty": 1.0, "value": [5e7, 2e7, 9e9, 9e9],
    })
    out = sec.insider_block(ins)
    assert out["net_market_buy_cr"] == 3.0            # 5 cr bought − 2 cr sold; off-market and pledges ignored
    assert out["buyers"] == 1 and out["sellers"] == 1


def test_deals_split_shorts_from_bulk_block():
    deals = pd.DataFrame({
        "date": pd.to_datetime(["2026-10-08", "2026-10-08", "2026-10-06", "2026-10-05"]),
        "kind": ["block", "block", "short", "short"], "client_name": ["X", "Y", None, None],
        "side": ["SELL", "BUY", "SELL", "SELL"], "qty": [100.0, 300.0, 50.0, 25.0], "price": [1e5, 1e5, None, None],
    })
    out = sec.deals_block(deals)
    assert len(out["rows"]) == 2 and all(r["kind"] == "block" for r in out["rows"])
    assert out["net_value_cr"] == 2.0                  # (300 − 100) × ₹1 lakh = ₹2 cr net buying
    assert out["short"] == {"days": 2, "qty": 75.0}


def test_ownership_change_over_window_and_dedup():
    sh = pd.DataFrame({
        "period_end": pd.to_datetime(["2025-12-31", "2026-03-31", "2026-06-30", "2026-06-30"]),
        "broadcast_ts": ["a", "b", "c", "d"],          # a revised June filing: the later one wins
        "promoter_pct": [50.0, 50.5, 51.0, 51.5], "fpi_pct": [20.0, 19.0, 18.0, 17.0], "mf_pct": [5.0, 6.0, 7.0, 8.0],
        "retail_pct": [10.0, 10.0, 10.0, 10.0], "total_holders": [1000.0, 1100.0, 1200.0, 1250.0], "retail_holders": 900.0,
    })
    out = sec.ownership_block(sh)
    assert len(out["quarters"]) == 3 and out["quarters"][0]["promoter_pct"] == 51.5
    assert out["change_over_window"]["fpi_pct"] == -3.0 and out["holders_change_pct"] == 25.0


def test_deals_block_counts_a_block_repeated_in_the_bulk_file_once():
    import pandas as pd
    t = {"date": pd.Timestamp("2026-10-12"), "client_name": "QUANT MUTUAL FUND", "side": "SELL", "qty": 1_100_000, "price": 915.0}
    out = sec.deals_block(pd.DataFrame([{**t, "kind": "block"}, {**t, "kind": "bulk"}]))
    assert len(out["rows"]) == 1 and out["rows"][0]["kind"] == "block" and out["net_value_cr"] == -100.65


def test_history_rows_bonus_ex_date_is_not_a_crash():
    # 1:1 bonus on day 3: the raw price halves; adjust() should detect it and the day's change stays near 0
    from shared.nse_panel import adjust
    raw = pd.DataFrame({
        "symbol": "XYZ", "series": "EQ", "date": pd.to_datetime(["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]),
        "open": [200.0, 202.0, 101.0, 102.0], "high": [203.0, 205.0, 103.0, 104.0], "low": [199.0, 200.0, 100.0, 101.0],
        "close": [202.0, 202.0, 102.0, 103.0], "prev_close": [200.0, 202.0, 101.0, 102.0], "avg_price": [201.0, 203.0, 101.5, 102.5],
        "volume": [1000, 1200, 2600, 2400], "turnover_lacs": [2.0, 2.4, 2.6, 2.5], "trades": [50, 60, 90, 80],
        "deliv_qty": [500, 600, 1300, 1000], "deliv_pct": [50.0, 50.0, 50.0, 41.7]})
    bars = adjust(raw)
    out = sec.history_rows(bars, bars.attrs.pop("corporate_actions"))
    rows = out["rows"]
    assert [r["date"] for r in rows] == ["2026-10-08", "2026-10-07", "2026-10-06", "2026-10-05"]   # newest first
    ex = rows[1]
    assert ex["close"] == 102.0                                   # as traded
    assert ex["change_pct"] == pytest.approx(0.99, abs=0.01)      # 202 → 102 after a 1:1 bonus: 101 → 102, not −50%
    assert ex["action_k"] == 0.5 and out["actions"] == [{"date": "2026-10-07", "k": 0.5}]
    assert rows[-1]["change_pct"] is None                         # nothing before the first bar
    s = out["summary"]
    assert s["sessions"] == 4 and s["return_pct"] == pytest.approx((103 / 101 - 1) * 100, abs=0.01)
    assert s["up_days"] == 2 and s["down_days"] == 0


def test_drawdown_stats_finds_the_deepest_fall():
    b = pd.DataFrame({"date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]),
                      "adj_close": [100.0, 120.0, 90.0, 110.0, 130.0, 117.0]})
    d = sec.drawdown_stats(b)
    assert d["max_dd_pct"] == -25.0 and d["dd_peak"] == "2026-01-02" and d["dd_trough"] == "2026-01-05"
    assert d["dd_now_pct"] == -10.0                                  # 117 vs the 130 peak
