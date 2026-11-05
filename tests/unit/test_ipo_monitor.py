"""IPO page (services/data-service/ipo_monitor.py): NSE parsing, listing scorecard, subscription buckets."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "data-service"))
import ipo_monitor as im  # noqa: E402


def test_parse_band_and_date():
    assert im.parse_band("Rs.258 to Rs.272") == (258.0, 272.0)
    assert im.parse_band("   272") == (272.0, 272.0)
    assert im.parse_band("-") == (None, None)
    assert im.parse_date("29-SEP-2026") == "2026-09-29" and im.parse_date("13-Oct-2026") == "2026-10-13"
    assert im.parse_date("-") is None


def test_parse_bids_picks_category_totals_not_subrows():
    detail = {"bidDetails": [
        {"category": "Qualified Institutional Buyers(QIBs)", "noOfTime": "115.7", "srNo": "1"},
        {"category": "Foreign Institutional Investors(FIIs)", "noOfTime": "", "srNo": "1(a)"},
        {"category": "Non Institutional Investors", "noOfTime": "91.2", "srNo": "2"},
        {"category": "Non Institutional Investors(Bid amount of more than Ten Lakh Rupees)", "noOfTime": "101.2", "srNo": "2.1"},
        {"category": "Retail Individual Investors(RIIs)", "noOfTime": "18.5", "srNo": "3"},
        {"category": "Total", "noOfTime": "61.9", "srNo": None}]}
    assert im.parse_bids(detail) == {"qib": 115.7, "nii": 91.2, "retail": 18.5, "employee": None, "total": 61.9}
    assert im.parse_bids({})["total"] is None


def test_parse_past_filters_kind_and_needs_listing():
    rows = [{"symbol": "AAA", "companyName": "A Ltd", "securityType": "EQ", "issuePrice": " 100", "listingDate": "05-OCT-2026",
             "ipoStartDate": "25-SEP-2026", "ipoEndDate": "29-SEP-2026", "priceRange": "Rs.95 to Rs.100"},
            {"symbol": "BBB", "securityType": "SME", "issuePrice": "50", "listingDate": "01-OCT-2026"},
            {"symbol": "CCC", "securityType": "EQ", "issuePrice": "-", "listingDate": "-"},
            {"symbol": "DDD", "securityType": "DEBT", "issuePrice": "1000", "listingDate": "01-OCT-2026"}]
    main = im.parse_past(rows, im.MAINBOARD)
    assert [r["symbol"] for r in main] == ["AAA"] and main[0]["issue_price"] == 100 and main[0]["kind"] == "Mainboard"
    assert [r["symbol"] for r in im.parse_past(rows, im.SME)] == ["BBB"]


def test_scorecard_listing_gain_and_post_listing_returns():
    past = [{"symbol": "AAA", "issue_price": 100.0, "listing_date": "2026-01-05"}]
    dates = pd.bdate_range("2026-01-05", periods=70)
    close = [120.0 + i for i in range(70)]
    px = pd.DataFrame({"symbol": "AAA", "date": dates, "open": [130.0] + close[:-1], "close": close})
    r = im.scorecard(past, px)[0]
    assert r["listing_gain_pct"] == pytest.approx(30.0)              # opened at 130 vs 100 issue
    assert r["listing_close_pct"] == pytest.approx(20.0)
    assert r["ret_20d_pct"] == pytest.approx((140 / 120 - 1) * 100)   # from the listing-day close
    assert r["ret_60d_pct"] == pytest.approx((180 / 120 - 1) * 100)
    assert r["since_issue_pct"] == pytest.approx(89.0) and r["sessions"] == 70
    none = im.scorecard(past, pd.DataFrame(columns=["symbol", "date", "open", "close"]))[0]
    assert none["listing_gain_pct"] is None and none["sessions"] == 0


def test_buckets_by_qib_subscription():
    rows = [{"qib": 5, "listing_gain_pct": -4.0, "ret_60d_pct": -10.0}, {"qib": 8, "listing_gain_pct": 2.0, "ret_60d_pct": None},
            {"qib": 150, "listing_gain_pct": 40.0, "ret_60d_pct": 5.0}, {"qib": None, "listing_gain_pct": 9.0}]
    b = {x["bucket"]: x for x in im.buckets(rows)}
    assert b["< 10×"]["n"] == 2 and b["< 10×"]["mean_listing_gain"] == -1.0 and b["< 10×"]["pct_listed_above"] == 50
    assert b["< 10×"]["n_60d"] == 1 and b["< 10×"]["mean_ret_60d"] == -10.0
    assert b["≥ 100×"]["n"] == 1 and b["10–50×"]["n"] == 0 and b["10–50×"]["mean_listing_gain"] is None


def test_scorecard_survives_a_split_after_listing():
    past = [{"symbol": "SPL", "issue_price": 100.0, "listing_date": "2026-01-05"}]
    dates = pd.bdate_range("2026-01-05", periods=30)
    close = [110.0] * 10 + [22.0] * 20                     # 1:5 split on day 10, price otherwise flat
    px = pd.DataFrame({"symbol": "SPL", "date": dates, "open": [105.0] + close[:-1], "close": close,
                       "adj_close": [22.0] * 30})            # adjusted series: flat
    r = im.scorecard(past, px)[0]
    assert r["listing_gain_pct"] == pytest.approx(5.0) and r["listing_close_pct"] == pytest.approx(10.0)
    assert r["ret_20d_pct"] == pytest.approx(0.0) and r["since_issue_pct"] == pytest.approx(10.0)
