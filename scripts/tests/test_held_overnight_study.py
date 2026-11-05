"""Held-overnight study: point-in-time returns, build-up classes, deal netting, statistics, verdicts."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import held_overnight_study as hs  # noqa: E402


def test_forward_returns_start_at_next_open():
    idx = pd.date_range("2024-01-01", periods=6, freq="B")
    op = pd.DataFrame({"A": [100, 110, 121, 133.1, 146.41, 161.051]}, index=idx)
    f = hs.forward_open_returns(op, 2)
    # signal after the close of day 0 → buy day-1 open (110), sell day-3 open (133.1)
    assert abs(f.iloc[0, 0] - (133.1 / 110 - 1)) < 1e-12
    assert f.iloc[-3:, 0].isna().all()          # no future data at the end of the sample


def test_buildup_classes_need_both_thresholds():
    assert hs.classify_buildup(0.05, 0.15) == "long build-up"
    assert hs.classify_buildup(0.05, -0.15) == "short covering"
    assert hs.classify_buildup(-0.05, 0.15) == "short build-up"
    assert hs.classify_buildup(-0.05, -0.15) == "long unwinding"
    assert hs.classify_buildup(0.02, 0.50) is None and hs.classify_buildup(0.05, 0.05) is None


def test_bulk_deal_netting_drops_round_trippers_and_flags_institutions():
    d = pd.DataFrame({
        "date": pd.to_datetime(["2024-03-01"] * 4), "symbol": ["ABC"] * 4,
        "client_name": ["HDFC MUTUAL FUND", "GRAVITON RESEARCH CAPITAL LLP", "GRAVITON RESEARCH CAPITAL LLP", "X LTD"],
        "side": ["BUY", "BUY", "SELL", "SELL"], "qty": [100000, 500000, 498000, 70000],
    })
    g = hs.net_bulk_deals(d).set_index("client_name")
    assert "GRAVITON RESEARCH CAPITAL LLP" not in g.index           # bought and sold the same day
    assert bool(g.loc["HDFC MUTUAL FUND", "institution"]) and g.loc["HDFC MUTUAL FUND", "direction"] == "buy"
    assert g.loc["X LTD", "direction"] == "sell" and not bool(g.loc["X LTD", "institution"])


def test_week_clustered_t_stat():
    dates = pd.Series(pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-08", "2024-01-15", "2024-01-22"]))
    ex = pd.Series([0.01, 0.03, 0.02, 0.02, 0.02])        # weekly means 0.02 each → zero dispersion
    mean, t, n = hs.week_clustered(ex, dates)
    assert n == 4 and abs(mean - 0.02) < 1e-12 and (np.isinf(t) or t > 1e6)


def test_verdict_requires_both_periods_and_cost_hurdle():
    cost = 0.01
    rows = [{"period": "discovery", "events": 50, "excess_pct": 1.5, "t_excess": 2.5},
            {"period": "holdout", "events": 40, "excess_pct": 1.4, "t_excess": 2.2}]
    assert hs.verdict(rows, cost).startswith("SUPPORTED")
    rows[1]["excess_pct"] = 0.6
    assert hs.verdict(rows, cost).startswith("REAL BUT TOO SMALL")
    rows[1]["t_excess"] = 1.1
    assert hs.verdict(rows, cost) == "NO RELIABLE EDGE"


def test_to_session_maps_to_next_trading_day_and_nat_beyond_data():
    idx = pd.DatetimeIndex(["2024-03-01", "2024-03-04", "2024-03-05"])     # Fri, Mon, Tue
    got = hs.to_session(pd.Series(pd.to_datetime(["2024-03-02", "2024-03-04", "2024-03-09", "1925-01-23"])), idx)
    assert got.iloc[0] == pd.Timestamp("2024-03-04")        # Saturday intimation → Monday session
    assert got.iloc[1] == pd.Timestamp("2024-03-04") and pd.isna(got.iloc[2])
    assert pd.isna(got.iloc[3])                              # typo dates before the data never map to day one


def _panel(n_days=320, syms=("A", "B", "C", "D", "E", "F")):
    idx = pd.date_range("2023-01-02", periods=n_days, freq="B")
    rng = np.random.default_rng(0)
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n_days, len(syms))), axis=0)), index=idx, columns=syms)
    return {"close": close, "open": close.shift(1).fillna(close), "series": pd.DataFrame("EQ", index=idx, columns=syms),
            "turnover_cr": pd.DataFrame(10.0, index=idx, columns=syms)}


def test_h4_keeps_only_key_people_market_purchases_above_ten_lakh():
    panel = _panel()
    day = panel["close"].index[200]
    insider = pd.DataFrame({
        "symbol": ["A", "B", "C", "D"],
        "category": ["Promoters", "Employees/Designated Employees", "Director", "Promoter Group"],
        "mode": ["Market Purchase", "Market Purchase", "Market Purchase", "ESOP"],
        "txn_type": ["Buy"] * 4, "value": [2_000_000, 5_000_000, 500_000, 9_000_000],
        "from_date": [day.date()] * 4, "to_date": [day.date()] * 4,
        "intimation_date": [day.date()] * 4,
    })
    ev = hs.h4_events(panel, insider, horizons=(20,))
    buys = ev[("H4 insider open-market BUY (≥ ₹10 lakh)", 20)]
    assert buys["symbol"].tolist() == ["A"] and buys["date"].iloc[0] == day


def test_h4_drops_disclosures_with_impossible_dates():
    panel = _panel()
    day = panel["close"].index[200]
    insider = pd.DataFrame({"symbol": ["A", "B"], "category": ["Promoters", "Promoters"],
                            "mode": ["Market Purchase"] * 2, "txn_type": ["Buy"] * 2, "value": [2_000_000] * 2,
                            "from_date": [day.date(), day.date()], "to_date": [day.date(), day.date()],
                            "intimation_date": [day.date(), (day + pd.Timedelta(days=400)).date()]})
    buys = hs.h4_events(panel, insider, horizons=(20,))[("H4 insider open-market BUY (≥ ₹10 lakh)", 20)]
    assert buys["symbol"].tolist() == ["A"]


def test_fresh_buys_need_ninety_quiet_days_including_history():
    buys = pd.DataFrame({"symbol": ["A", "A", "A", "B"],
                         "date": pd.to_datetime(["2026-08-01", "2026-10-05", "2027-02-01", "2026-10-02"])})
    fresh = hs.fresh_buys(buys)
    # A's October buy follows an August buy (65 days) → not fresh; February is 119 days later → fresh
    assert sorted(zip(fresh["symbol"], fresh["date"].dt.strftime("%Y-%m-%d"))) == [
        ("A", "2026-08-01"), ("A", "2027-02-01"), ("B", "2026-10-02")]


def test_forward_verdict_waits_for_enough_events():
    rows = [{"period": "discovery", "events": 0},
            {"period": "holdout", "events": 40, "excess_pct": 3.0, "t_excess": 3.0, "t_nw": 2.5}]
    assert hs.forward_verdict(rows, 0.01) == "FORWARD TEST · 40 of 100 events so far"
    rows[1]["events"] = 120
    assert hs.forward_verdict(rows, 0.01).startswith("SUPPORTED")
    rows[1]["t_nw"] = 1.5
    assert hs.forward_verdict(rows, 0.01) == "NO RELIABLE EDGE"


def test_h6_needs_readable_filings_in_both_quarters():
    panel = _panel()
    q = lambda sym, end, stamp, holders, fpi, mf: {"symbol": sym, "period_end": end, "broadcast_ts": stamp,  # noqa: E731
                                                   "total_holders": holders, "fpi_pct": fpi, "mf_pct": mf}
    shp = pd.DataFrame([
        q("A", "2023-09-30", "19-OCT-2023 18:00:00", 1000, 10.0, 5.0),
        q("A", "2023-12-31", "20-JAN-2024 18:00:00", 950, 12.0, 5.0),        # accumulation
        q("B", "2023-09-30", "19-OCT-2023 18:00:00", 1000, 10.0, 5.0),
        q("B", "2023-12-31", "20-JAN-2024 18:00:00", 950, np.nan, np.nan),   # categories unread
        q("C", "2023-09-30", "19-OCT-2023 18:00:00", 1000, np.nan, np.nan),  # unread → would fake +30 pp
        q("C", "2023-12-31", "20-JAN-2024 18:00:00", 950, 25.0, 5.0),
    ])
    ev = hs.h6_events(panel, shp, horizons=(20,))[("H6 accumulation (holders down, FPI+MF up)", 20)]
    assert ev["symbol"].tolist() == ["A"]
    assert ev["date"].iloc[0] == pd.Timestamp("2024-01-22")       # Saturday broadcast → Monday session


def test_newey_west_is_more_conservative_on_overlapping_series():
    rng = np.random.default_rng(1)
    shocks = rng.normal(0.002, 0.01, 400)
    overlapping = pd.Series(np.convolve(shocks, np.ones(4) / 4, mode="valid"))   # 4-week windows overlap
    plain = overlapping.mean() / (overlapping.std(ddof=1) / np.sqrt(len(overlapping)))
    assert abs(hs.newey_west_t(overlapping, 4)) < abs(plain)


def test_verdict_uses_newey_west_when_present():
    rows = [{"period": "discovery", "events": 50, "excess_pct": 1.5, "t_excess": 2.5, "t_nw": 2.1},
            {"period": "holdout", "events": 40, "excess_pct": 1.4, "t_excess": 2.2, "t_nw": 1.8}]
    assert hs.verdict(rows, 0.01) == "NO RELIABLE EDGE"
