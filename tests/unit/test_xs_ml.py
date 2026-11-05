"""Cross-sectional labels (shared/xs_labels.py) and point-in-time features (shared/xs_features.py)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared import xs_features as xf  # noqa: E402
from shared import xs_labels as xl  # noqa: E402


def _panel(n=320, syms=("A", "B", "C", "D"), start="2019-06-03", seed=0):
    idx = pd.bdate_range(start, periods=n)
    rng = np.random.default_rng(seed)
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, len(syms))), axis=0)), index=idx, columns=list(syms))
    open_ = close.shift(1).fillna(close) * (1 + rng.normal(0, 0.002, close.shape))
    return {"close": close, "open": open_, "high": np.maximum(close, open_) * 1.01, "low": np.minimum(close, open_) * 0.99,
            "volume": pd.DataFrame(1e5, index=idx, columns=close.columns),
            "deliv_pct": pd.DataFrame(50.0, index=idx, columns=close.columns),
            "turnover_cr": pd.DataFrame(10.0, index=idx, columns=close.columns),
            "series": pd.DataFrame("EQ", index=idx, columns=close.columns)}


# ── labels ────────────────────────────────────────────────────────────────────

def test_forward_returns_enter_next_open_and_exit_at_last_trade_if_suspended():
    idx = pd.bdate_range("2024-01-01", periods=6)
    op = pd.DataFrame({"A": [100, 110, 120, 130, 140, 150], "B": [50, 55, np.nan, np.nan, np.nan, np.nan]}, index=idx)
    f = xl.forward_open_returns(op, 2)
    assert abs(f.at[idx[0], "A"] - (130 / 110 - 1)) < 1e-12          # buy day-1 open, sell day-3 open
    assert abs(f.at[idx[0], "B"] - 0.0) < 1e-12                        # suspended: exit at the last traded open
    assert np.isnan(f.at[idx[1], "B"])                                 # cannot enter a suspended stock
    assert f["A"].iloc[-3:].isna().all()


def test_clean_windows_drop_data_breaks_inside_the_window_only():
    idx = pd.bdate_range("2024-01-01", periods=8)
    c = pd.DataFrame({"A": [100, 100, 100, 100, 200, 200, 200, 200]}, index=idx)   # +100% on day 4
    ok = xl.clean_windows(c, 2)["A"]
    assert ok.iloc[0] and not ok.iloc[1] and not ok.iloc[2] and not ok.iloc[3] and ok.iloc[4]


def test_excess_and_rank_use_universe_members_only():
    idx = pd.bdate_range("2024-01-01", periods=1)
    fwd = pd.DataFrame({"A": [0.10], "B": [0.00], "C": [-0.10], "D": [5.0]}, index=idx)
    uni = pd.DataFrame({"A": [True], "B": [True], "C": [True], "D": [False]}, index=idx)
    ex = xl.excess_returns(fwd, uni)
    assert np.isnan(ex.at[idx[0], "D"]) and abs(ex.loc[idx[0], ["A", "B", "C"]].sum()) < 1e-12
    assert xl.rank_label(ex).loc[idx[0], ["A", "B", "C"]].tolist() == [1.0, 2 / 3, 1 / 3]


def test_legacy_label_matches_production_rule():
    idx = pd.bdate_range("2024-01-01", periods=7)
    c = pd.DataFrame({"A": [100, 101, 102, 103, 104, 100.1, 100.2]}, index=idx)
    lab = xl.legacy_direction_label(c, h=5, hurdle_pct=0.15)["A"]
    assert lab.iloc[0] == 0.0 and lab.iloc[1] == 0.0 and lab.iloc[2:].isna().all()   # +0.10% < hurdle


# ── features: no look-ahead ──────────────────────────────────────────────────

def test_technical_features_never_change_when_the_future_changes():
    p = _panel()
    base = xf.technical_features(p)
    q = {k: v.copy() for k, v in p.items()}
    for k in ("close", "open", "high", "low"):
        q[k].iloc[-10:] *= 1.5
    moved = xf.technical_features(q)
    cut = p["close"].index[-11]
    for name in xf.TECHNICAL:
        pd.testing.assert_frame_equal(base[name].loc[:cut], moved[name].loc[:cut], check_names=False, obj=name)


def test_mtf_is_visible_one_session_after_its_date():
    p = _panel(start="2022-01-03")
    d = p["close"].index
    mtf = pd.DataFrame({"date": [d[250]] * 4, "symbol": list("ABCD"), "qty_financed": [1e4] * 4})
    f = xf.market_wide_features(p, None, None, mtf)["mtf_intensity"]
    assert np.isnan(f.at[d[250], "A"]) and f.at[d[251], "A"] == 1e4 / 1e5
    assert _panel(start="2019-06-03")["close"].pipe(lambda c: xf.market_wide_features(
        {**_panel(start="2019-06-03")}, None, None, mtf.assign(date=c.index[250]))["mtf_intensity"]).isna().all().all()


def test_event_features_are_unknown_before_collection_and_zero_after():
    p = _panel(start="2019-06-03")
    d = p["close"].index
    deals = pd.DataFrame({"date": [d[200]], "kind": ["bulk"], "symbol": ["A"], "client_name": ["X LLP"],
                          "side": ["BUY"], "qty": [1e5]})
    f = xf.market_wide_features(p, None, deals, None)["bulk_other_buy_20d"]
    assert f.loc[:"2019-09-30"].isna().all().all()
    assert f.at[d[200], "A"] == 1 and f.at[d[219], "A"] == 1 and f.at[d[220], "A"] == 0 and f.at[d[200], "B"] == 0


def test_insider_features_use_intimation_date_and_coverage():
    p = _panel(start="2019-06-03")
    d = p["close"].index
    ins = pd.DataFrame({"symbol": ["A", "A", "B"], "category": ["Promoters", "Director", "Promoters"],
                        "mode": ["Market Purchase"] * 3, "value": [5e6, 5e6, 5e6],
                        "from_date": [d[200].date(), d[200].date(), d[200].date()],
                        "to_date": [d[200].date(), d[200].date(), d[200].date()],
                        "intimation_date": [d[202].date(), (d[200] + pd.Timedelta(days=500)).date(), d[202].date()]})
    f = xf.per_company_features(p, ins, None, covered={"A", "C"})
    buy = f["insider_buy_63d"]
    assert buy.at[d[201], "A"] == 0 and abs(buy.at[d[202], "A"] - np.log1p(50)) < 1e-9   # typo date dropped
    assert np.isnan(buy.at[d[202], "B"])                     # B not collected → unknown, not zero
    assert f["insider_fresh_buy_21d"].at[d[202], "A"] == 1


def test_shareholding_is_known_from_broadcast_and_replaced_by_the_next_filing():
    p = _panel(start="2021-06-01", n=320)
    shp = pd.DataFrame({
        "symbol": ["A", "A", "A"], "period_end": ["2021-06-30", "2021-09-30", "2021-12-31"],
        "broadcast_ts": ["20-JUL-2021 18:00:00", "19-OCT-2021 18:00:00", "18-JAN-2022 18:00:00"],
        "total_holders": [1000, 900, 950], "fpi_pct": [10.0, 12.0, np.nan], "mf_pct": [5.0, 5.0, np.nan],
        "retail_pct": [20.0, 19.0, 19.5], "promoter_pct": [50.0, 50.0, 49.0]})
    f = xf.per_company_features(p, None, shp, covered={"A"})
    d_inst = f["shp_d_inst"]["A"]
    assert np.isnan(d_inst.loc["2021-10-18"]) and d_inst.loc["2021-10-19"] == 2.0
    assert d_inst.loc["2021-12-31"] == 2.0 and np.isnan(d_inst.loc["2022-01-18"])      # unread filing ≠ old value
    assert abs(f["shp_d_holders"]["A"].loc["2022-01-18"] - (950 / 900 - 1)) < 1e-12


def test_stack_ranks_within_the_universe_on_each_date():
    idx = pd.bdate_range("2024-01-01", periods=2)
    feats = {"ret_1d": pd.DataFrame({"A": [3.0, 1.0], "B": [2.0, 2.0], "C": [1.0, 3.0]}, index=idx),
             "fno": pd.DataFrame({"A": [1.0, 1.0], "B": [0.0, 0.0], "C": [1.0, 1.0]}, index=idx)}
    uni = pd.DataFrame({"A": [True, True], "B": [True, True], "C": [False, True]}, index=idx)
    long = xf.stack(feats, idx, uni).set_index(["date", "symbol"])
    assert len(long) == 5 and ("2024-01-01", "C") not in long.index
    assert long.loc[(idx[0], "A"), "ret_1d"] == 1.0 and long.loc[(idx[0], "B"), "ret_1d"] == 0.5
    assert long.loc[(idx[1], "C"), "ret_1d"] == 1.0 and long.loc[(idx[1], "B"), "fno"] == 0.0     # flags stay raw
