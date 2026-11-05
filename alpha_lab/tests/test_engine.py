"""alpha_lab engine: costs, staleness, hedge lots and sleeve behave as Amendments v2 specify."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
from backtest import engine  # noqa: E402


def panel_of(close: pd.DataFrame) -> dict:
    return {"close": close, "open": close.copy(), "raw_close": close.copy(),
            "series": close.notna().map(lambda b: "EQ" if b else None)}


def flat_panel(n=140, px=100.0, syms=("AAA", "BBB", "CCC", "DDD")):
    idx = pd.bdate_range("2024-01-01", periods=n)
    return panel_of(pd.DataFrame(px, index=idx, columns=list(syms)))


def test_costs_and_cash_accrual_on_a_flat_tape():
    p = flat_panel()
    nifty = pd.Series(100.0, index=p["close"].index)
    cfg = engine.EngineConfig(capital=1_000_000, cash_rate=0.06, n_positions=4, max_weight=0.25)
    res = engine.run(p, nifty, [10, 50, 90], lambda s: (["AAA", "BBB", "CCC", "DDD"], True), cfg)
    # prices never move: equity = capital − entry costs + interest on the residual cash
    assert res.costs_paid > 0
    # fully invested (4 × 25%), flat prices: equity ≈ capital − costs (cash interest ≈ 0)
    assert abs(res.equity.iloc[-1] - (cfg.capital - res.costs_paid)) < 0.002 * cfg.capital
    assert (res.rebalances["risk_on"]).all()
    # second and third rebalance trade ~nothing (already at target)
    assert res.rebalances["traded"].iloc[1] < res.rebalances["traded"].iloc[0] * 0.05


def test_stale_name_is_force_sold_and_then_marked_zero():
    p = flat_panel(n=200)
    c = p["close"]
    c.loc[c.index[30]:, "DDD"] = np.nan                            # DDD stops trading at row 30
    nifty = pd.Series(100.0, index=c.index)
    cfg = engine.EngineConfig(capital=1_000_000, n_positions=4, max_weight=0.25)
    res = engine.run(p, nifty, [10, 60, 150], lambda s: (["AAA", "BBB", "CCC", "DDD"], True), cfg)
    assert "forced stale exits: 1" in res.notes[0]                 # sold at the 60-row rebalance
    # had it NOT been sold, the zero-out after 60 stale sessions would have cratered equity ~25%
    assert res.equity.iloc[-1] > 0.9 * cfg.capital


def test_hedge_rounds_to_whole_lots_and_neutralises_the_index_move():
    n = 120
    idx = pd.bdate_range("2024-01-01", periods=n)
    nif = pd.Series(np.linspace(20000, 16000, n), index=idx)       # −20% slide
    book = pd.DataFrame(np.tile((nif / nif.iloc[0] * 100).to_numpy()[:, None], (1, 4)),
                        index=idx, columns=["AAA", "BBB", "CCC", "DDD"])   # book falls with the index
    p = panel_of(book)
    cfg = engine.EngineConfig(capital=5_000_000, n_positions=4, hedge=True, sleeve_frac=0.15,
                              cash_rate=0.0, slippage=0.0, max_weight=0.25)
    res = engine.run(p, nif, [5, 45, 85], lambda s: (["AAA", "BBB", "CCC", "DDD"], False), cfg)
    r0 = res.rebalances.iloc[0]
    lots = r0["hedge_lots"]
    assert lots == round((r0["hedge"] + r0["residual_exposure"]) / (75 * nif.iloc[6])) and lots == 3
    # hedged book on a market-tracking tape: end equity within a few % of start (costs + lot residual only)
    assert abs(res.equity.iloc[-1] / cfg.capital - 1) < 0.04
    # unhedged same tape loses ~17% (85% × −20%)
    cfg2 = engine.EngineConfig(capital=5_000_000, n_positions=4, hedge=False, cash_rate=0.0, max_weight=0.25)
    res2 = engine.run(p, nif, [5, 45, 85], lambda s: (["AAA", "BBB", "CCC", "DDD"], True), cfg2)
    assert res2.equity.iloc[-1] < 0.86 * cfg.capital


def test_ew_benchmark_tracks_member_mean():
    p = flat_panel(n=60)
    p["close"]["AAA"] *= np.linspace(1, 1.2, 60)                   # AAA +20%, others flat
    ew = engine.ew_benchmark(p, [5, 40], lambda s: pd.Index(["AAA", "BBB"]))
    total = ew.iloc[-1] / ew.iloc[0] - 1
    assert 0.08 < total < 0.11                                     # ≈ mean of (+~19% from row 6, 0%)


def test_gate_a_fails_on_breadth_beta_alone():
    idx = pd.bdate_range("2020-01-01", periods=1300)
    up = pd.Series(np.linspace(100, 220, 1300), index=idx)         # strategy +120%
    nif = pd.Series(np.linspace(100, 160, 1300), index=idx)        # NIFTY +60%
    ew = pd.Series(np.linspace(100, 230, 1300), index=idx)         # EW universe +130% — beats the strategy
    g = engine.gate_a(up, nif, ew, decisions=60)
    assert not g["pass"] and not g["checks"][[k for k in g["checks"] if k.startswith("1b")][0]]
