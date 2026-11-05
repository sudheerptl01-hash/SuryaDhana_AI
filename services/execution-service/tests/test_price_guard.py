"""Paper/live orders must be priced near the real market — the paper engine books at
the SUBMITTED price, so an unchecked price creates fictitious positions (a June-2026
test booked RELIANCE @ ₹100 and SKFINDIA @ ₹50 → +2,967% phantom P&L)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from live_execution import ExecutionEngine, ExecutionMode  # noqa: E402


def _engine(tmp_path, ref: float, guard: float = 10.0) -> ExecutionEngine:
    eng = ExecutionEngine(mode=ExecutionMode.PAPER, db_path=str(tmp_path / "p.db"),
                          initial_equity=1_000_000.0, price_guard_pct=guard)
    eng._reference_price = lambda symbol: ref  # no network in tests
    return eng


def _buy(eng, price):
    return asyncio.run(eng.place_order("RELIANCE", "BUY", 10, price, "Manual"))


def test_far_off_market_price_is_rejected(tmp_path):
    eng = _engine(tmp_path, ref=1400.0)
    r = _buy(eng, 100.0)
    assert r["status"] == "REJECTED" and "away from the market price" in r["error"]
    assert not eng._positions


def test_price_near_market_is_filled(tmp_path):
    eng = _engine(tmp_path, ref=1400.0)
    r = _buy(eng, 1405.0)
    assert r.get("status") == "FILLED"
    assert "RELIANCE" in eng._positions


def test_unknown_market_price_is_rejected(tmp_path):
    eng = _engine(tmp_path, ref=0.0)
    r = _buy(eng, 1400.0)
    assert r["status"] == "REJECTED" and "No market reference price" in r["error"]


def test_guard_can_be_disabled_explicitly(tmp_path):
    eng = _engine(tmp_path, ref=0.0, guard=0)
    assert _buy(eng, 100.0).get("status") == "FILLED"
