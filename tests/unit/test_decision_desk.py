"""Decision Desk (paper): month-end brief, open fills, risk-off, emergency stop, splits — offline."""
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from shared.decision_desk import Desk, next_weekday  # noqa: E402
from shared.momentum import StrategyConfig  # noqa: E402
from shared.trading_costs import PROFILES, CostModel  # noqa: E402

IDX = pd.bdate_range("2023-01-02", periods=420)           # ends 2024-08-12
SYMS = [f"S{i:02d}" for i in range(40)]


def _market(crash_after: pd.Timestamp | None = None, nifty_down_after: pd.Timestamp | None = None,
            split: tuple[str, pd.Timestamp] | None = None):
    rng = np.random.default_rng(3)
    drift = np.linspace(0.0025, -0.0005, len(SYMS))
    rets = drift + rng.normal(0, 0.012, (len(IDX), len(SYMS)))
    close = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=IDX, columns=SYMS)
    if crash_after is not None:
        close.loc[close.index > crash_after] *= 0.6
    raw = close.copy()
    ca = pd.DataFrame(columns=["symbol", "date", "k", "source"])
    if split:
        sym, d = split
        raw.loc[raw.index >= d, sym] = raw.loc[raw.index >= d, sym] / 2     # real prices halve
        ca = pd.DataFrame([{"symbol": sym, "date": d, "k": 0.5, "source": "test"}])
        close.loc[close.index < d, sym] *= 1.0                              # adjusted series stays smooth
    opn = close.shift(1).fillna(close) * 1.001
    nifty = pd.Series(np.linspace(10_000, 14_000, len(IDX)), index=IDX)
    if nifty_down_after is not None:
        nifty.loc[nifty.index > nifty_down_after] = 5_000
    panel = {"open": opn, "high": close * 1.01, "low": close * 0.99, "close": close, "raw_close": raw,
             "volume": close * 0 + 1e6, "turnover_cr": close * 0 + 50.0, "deliv_pct": close * 0 + 50.0,
             "series": pd.DataFrame("EQ", index=IDX, columns=SYMS), "corporate_actions": ca}
    return panel, nifty


def _desk(tmp_path, market, **cfg) -> Desk:
    panel, nifty = market

    def loader(start):                                    # time travel: only data up to "today"
        cut = loader.today
        p = {k: (v[v.index <= pd.Timestamp(cut)] if isinstance(v, pd.DataFrame) and k != "corporate_actions" else v)
             for k, v in panel.items()}
        return p, nifty[nifty.index <= pd.Timestamp(cut)]
    loader.today = IDX[300].date()
    d = Desk(tmp_path / "desk.db", StrategyConfig(n=10, overlay="nifty200", sector_cap=None, **cfg),
             CostModel(PROFILES["icici_moneysaver"]), loader, start_capital=500_000)
    d._loader = loader
    return d


def _run(d: Desk, day) -> dict:
    d._loader.today = day
    return d.daily(day)


def _month_end_session(after: pd.Timestamp) -> pd.Timestamp:
    s = pd.Series(IDX, index=IDX)
    ends = s.groupby(IDX.to_period("M")).last()
    return ends[ends > after].iloc[0]


def test_month_end_brief_then_open_fills(tmp_path):
    d = _desk(tmp_path, _market())
    first = _run(d, IDX[300].date())
    assert first["plan"] is None and first["sessions_marked"] == 1          # mid-month start: no brief yet
    me = _month_end_session(IDX[300])
    days = IDX[(IDX > IDX[300]) & (IDX <= me)]
    for dd in days:
        res = _run(d, dd.date())
    assert res["plan"] is not None and res["plan"]["kind"] == "REBALANCE"
    assert _run(d, me.date())["plan"] is None                               # idempotent: one brief per month
    st = d.status()
    plan = st["plans"][0]
    buys = [o for o in plan["orders"] if o["side"] == "BUY"]
    assert len(buys) == 10 and all(o["reason"].startswith("Momentum rank") for o in buys)
    nxt = IDX[IDX.get_loc(me) + 1]
    ex = _run(d, nxt.date())
    assert ex["executions"] and ex["executions"][0]["pending"] == 0
    st = d.status()
    assert len(st["positions"]) == 10 and st["plans"][0]["status"] == "EXECUTED"
    invested = sum(p["value"] for p in st["positions"])
    assert invested == pytest.approx(0.66 * 500_000, rel=0.08)             # equity share 66%
    assert st["latest"]["nav"] < 500_000 * 1.05 and st["meta"]["cash"] > 0


def test_risk_off_brief_sells_everything(tmp_path):
    me1 = _month_end_session(IDX[300])
    me2 = _month_end_session(me1 + pd.Timedelta(days=1))
    d = _desk(tmp_path, _market(nifty_down_after=me1 + pd.Timedelta(days=5)))
    for dd in IDX[(IDX >= IDX[300]) & (IDX <= IDX[IDX.get_loc(me2) + 1])]:
        _run(d, dd.date())
    plans = d.status()["plans"]
    riskoff = plans[0]
    assert riskoff["risk_on"] == 0 and all(o["side"] == "SELL" for o in riskoff["orders"])
    assert "200-day" in riskoff["orders"][0]["reason"]
    assert d.status()["positions"] == []


def test_emergency_stop_liquidates_and_needs_manual_reenable(tmp_path):
    me = _month_end_session(IDX[300])
    crash = IDX[IDX.get_loc(me) + 3]
    d = _desk(tmp_path, _market(crash_after=crash), equity_share=1.0)
    out = None
    for dd in IDX[(IDX >= IDX[300]) & (IDX <= IDX[IDX.get_loc(crash) + 2])]:
        r = _run(d, dd.date())
        out = r if r["emergency"] else out
    assert out and out["emergency"]
    st = d.status()
    assert st["meta"]["stopped"] == 1 and st["positions"] == []
    assert any(p["kind"] == "EMERGENCY_EXIT" and p["status"] == "EXECUTED" for p in st["plans"])
    assert d.reenable()["stopped"] is False and d.status()["meta"]["stopped"] == 0


def test_split_on_held_stock_changes_qty_not_value(tmp_path):
    me = _month_end_session(IDX[300])
    d = _desk(tmp_path, _market())
    for dd in IDX[(IDX >= IDX[300]) & (IDX <= IDX[IDX.get_loc(me) + 1])]:
        _run(d, dd.date())
    held = d.status()["positions"][0]["symbol"]
    split_day = IDX[IDX.get_loc(me) + 5]
    d2 = _desk(tmp_path / "b", _market(split=(held, split_day)))
    for dd in IDX[(IDX >= IDX[300]) & (IDX <= split_day)]:
        _run(d2, dd.date())
    pos = {p["symbol"]: p for p in d2.status()["positions"]}
    pos1 = {p["symbol"]: p for p in d.status()["positions"]}
    assert pos[held]["qty"] == pytest.approx(2 * pos1[held]["qty"])
    nav = pd.DataFrame(d2.status()["nav"]).set_index("date")["nav"]
    assert nav.pct_change().abs().max() < 0.1                               # no fake −50% on the split day


def test_next_weekday():
    assert next_weekday(date(2026, 9, 25)) == date(2026, 9, 28)             # Fri → Mon
