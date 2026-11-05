"""Phase B allocator: selection buffer, trade accounting, FIFO tax, whole shares, simulation."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import phase_b_allocator as pb  # noqa: E402
from shared.trading_costs import PROFILES, CostModel  # noqa: E402

CM = CostModel(PROFILES["icici_moneysaver"])


def test_select_top_n_with_buffer():
    score = pd.Series({f"S{i}": 100 - i for i in range(20)})         # S0 best … S19 worst
    assert pb.select(score, set(), 3) == ["S0", "S1", "S2"]
    # S4 (rank 5) is held: inside 1.5·3 = 4.5? no → dropped; S3 (rank 4) held → kept
    assert pb.select(score, {"S3"}, 3) == ["S3", "S0", "S1"]
    assert pb.select(score, {"S4"}, 3) == ["S0", "S1", "S2"]


def test_buy_whole_shares_and_costs_then_sell_books_gain():
    book = pb.Book(cash=100_000)
    day = pd.Timestamp("2024-01-02")
    pb.buy(book, "X", 20_000, adj_px=500.0, raw_px=500.0, day=day, cm=CM)
    assert book.units["X"] == pytest.approx(40)                    # 20,000 / 500
    buy_cost = CM.leg(20_000, "buy").total
    assert book.cash == pytest.approx(100_000 - 20_000 - buy_cost)
    pb.sell(book, "X", 40, 550.0, pd.Timestamp("2024-06-03"), CM)
    sell_cost = CM.leg(22_000, "sell").total
    assert "X" not in book.units
    assert book.cash == pytest.approx(100_000 - 20_000 - buy_cost + 22_000 - sell_cost)
    st = book.realized["FY2025"]["st"]
    assert st == pytest.approx(22_000 - 20_000 - buy_cost - sell_cost)
    before = book.cash
    pb.settle_tax(book, "FY2025")
    assert before - book.cash == pytest.approx(st * 0.20 * 1.04, abs=0.01)   # tax rounded to paise


def test_unaffordable_share_is_skipped():
    book = pb.Book(cash=5_000)
    pb.buy(book, "MRF", 5_000, adj_px=130_000.0, raw_px=130_000.0, day=pd.Timestamp("2024-01-02"), cm=CM)
    assert book.units == {} and book.skipped_unaffordable == 1 and book.cash == 5_000


def test_short_term_loss_offsets_long_term_gain():
    book = pb.Book(cash=0)
    book.realized["FY2025"] = {"st": -50_000.0, "lt": 300_000.0}
    pb.settle_tax(book, "FY2025")
    assert book.taxes == pytest.approx((250_000 - 125_000) * 0.125 * 1.04)


def _toy_panel(n_days=320):
    idx = pd.bdate_range("2023-01-02", periods=n_days)
    rng = np.random.default_rng(7)
    cols = [f"S{i}" for i in range(6)]
    drift = np.linspace(0.002, -0.001, 6)                              # S0 strongest trend
    close = pd.DataFrame(100 * np.exp(np.cumsum(drift + rng.normal(0, 0.01, (n_days, 6)), axis=0)),
                         index=idx, columns=cols)
    return {"open": close.shift(1).fillna(close), "close": close, "raw_close": close,
            "series": pd.DataFrame("EQ", index=idx, columns=cols),
            "turnover_cr": pd.DataFrame(50.0, index=idx, columns=cols)}


def test_simulation_is_self_consistent_and_picks_momentum():
    panel = _toy_panel()
    sig = pb.signals(panel)
    nifty = panel["close"].mean(axis=1)
    start = panel["close"].index[270]
    eq, book = pb.simulate(pb.Variant("mom_121", 2, "none"), panel, sig, nifty, 100_000, CM, start)
    assert eq.iloc[0] > 0 and np.isfinite(eq).all()
    # no fake ₹0 valuation of names bought on a rebalance day: no one-day move > 20% on a calm toy panel
    assert eq.pct_change().abs().max() < 0.2
    assert book.trades > 0 and book.costs > 0
    assert "S0" in book.units                                          # strongest trend is held
    # book equity = cash + holdings at last close
    last = panel["close"].iloc[-1]
    assert eq.iloc[-1] == pytest.approx(book.cash + sum(u * last[s] for s, u in book.units.items()))


def test_deflated_sharpe_penalises_many_trials():
    one = pb.deflated_sharpe(1.0, 1000, 0.0, 0.0, [1.0])
    many = pb.deflated_sharpe(1.0, 1000, 0.0, 0.0, list(np.linspace(-0.5, 1.0, 24)))
    assert one > many and 0 <= many <= 1
