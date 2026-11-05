"""The 15-minute Breeze pilot (PLAN 1.1 ``iv_intraday``, §0.9 / §0.11): never a call without the budget ledger, never outside
09:20–15:30 IST, never without a live session; with a fake chain + a counting ledger it writes the parquet part and
``iv_intraday`` rows with IV from the bid/ask mid; a refusing ledger stops the tick before the SDK method runs."""
from __future__ import annotations

# ruff: noqa: DTZ001
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

from data_health import db  # noqa: E402
from fo_iv import black76 as b76  # noqa: E402
from fo_iv import intraday  # noqa: E402
from fo_iv.schema import CASTS, COLUMNS  # noqa: E402

TS = datetime(2026, 11, 5, 5, 0)            # 10:30 IST on a Thursday
DAY = date(2026, 11, 5)
EXPIRY = date(2026, 11, 9)


class _Decision:
    def __init__(self, allowed: bool, reason: str = "ok") -> None:
        self.allowed, self.reason, self.retry_after_s = allowed, reason, None if allowed else 30.0


class _Exceeded(Exception):
    pass


_Exceeded.__name__ = "BudgetExceeded"


class FakeLedger:
    def __init__(self, allow: bool = True, cap: int | None = None) -> None:
        self.allow, self.cap, self.acquired = allow, cap, 0

    def decide(self, caller: str, method: str = "") -> _Decision:
        return _Decision(self.allow, "ok" if self.allow else "day cap reached")

    @contextmanager
    def guard(self, caller: str, method: str = ""):
        if not self.allow or (self.cap is not None and self.acquired >= self.cap):
            raise _Exceeded("cap")
        self.acquired += 1
        yield _Decision(True)


class FakeBreeze:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_option_chain_quotes(self, **kw):
        self.calls.append((kw["stock_code"], kw["expiry_date"], kw["right"]))
        f, t = 24000.0, (EXPIRY - DAY).days / 365
        rows = []
        for k in range(23000, 25001, 100):
            call = kw["right"] == "call"
            px = b76.price(f, k, t, 0.14, call, 0.065)
            rows.append({"strike_price": k, "ltp": round(px, 2), "best_bid_price": round(px * 0.995, 2), "best_offer_price": round(px * 1.005, 2),
                         "best_bid_quantity": "65", "best_offer_quantity": "65", "open_interest": 1000.0, "chnge_oi": 10.0, "total_quantity_traded": "100",
                         "spot_price": "23950.0", "ltt": "05-Nov-2026 10:29:59", "expiry_date": "09-Nov-2026", "right": "Call" if call else "Put"})
        return {"Success": rows, "Status": 200}


@pytest.fixture
def store(tmp_path: Path):
    from storage.duckdb_store import DuckDBStore

    s = DuckDBStore(str(tmp_path / "iv.duckdb"))
    db.upsert(s, "iv_expiry_daily", pd.DataFrame([{"date": DAY - timedelta(days=1), "symbol": sym, "expiry": e, "dte": (e - DAY).days + 1, "atm_iv": 14.0,
                                                   "model_version": "t", "first_seen_at": TS} for sym in ("NIFTY", "BANKNIFTY")
                                                  for e in (EXPIRY, EXPIRY + timedelta(days=7))]), COLUMNS["iv_expiry_daily"], CASTS["iv_expiry_daily"])
    yield s
    s.close()


def test_window_and_fail_closed_rules(store, tmp_path):
    breeze = FakeBreeze()
    out = intraday.snapshot(store, breeze, None, now=TS, parquet_root=tmp_path / "chain")
    assert out["status"] == "skipped" and "budget ledger" in out["reason"] and breeze.calls == []          # no ledger → no call
    out = intraday.snapshot(store, None, FakeLedger(), now=TS, parquet_root=tmp_path / "chain")
    assert out["status"] == "skipped" and "not live" in out["reason"]
    out = intraday.snapshot(store, breeze, FakeLedger(), now=TS, parquet_root=tmp_path / "chain", is_live=lambda: False)
    assert out["status"] == "skipped" and "not live" in out["reason"] and breeze.calls == []
    out = intraday.snapshot(store, breeze, FakeLedger(), now=datetime(2026, 11, 5, 12, 0), parquet_root=tmp_path / "chain")   # 17:30 IST
    assert out["status"] == "skipped" and "outside" in out["reason"] and breeze.calls == []
    out = intraday.snapshot(store, breeze, FakeLedger(allow=False), now=TS, parquet_root=tmp_path / "chain")
    assert out["status"] == "skipped" and "refused" in out["reason"] and breeze.calls == []                # the dry run refuses
    assert intraday.in_window(datetime(2026, 11, 7, 10, 0)) is False                                          # Saturday


def test_a_tick_writes_parquet_and_iv_rows_from_the_mid(store, tmp_path):
    breeze, ledger = FakeBreeze(), FakeLedger()
    out = intraday.snapshot(store, breeze, ledger, now=TS, parquet_root=tmp_path / "chain")
    assert out["status"] == "ok" and out["calls"] == 8 == ledger.acquired and out["refused"] == 0             # 2 indices × 2 expiries × 2 sides
    assert out["rows"] > 0 and (tmp_path / "chain" / DAY.isoformat() / "part-0000.parquet").exists()
    rows = store.read("SELECT symbol, expiry, strike, opt_type, mid, iv, forward, source, model_version, r FROM iv_intraday WHERE symbol = 'NIFTY' AND expiry = ?", [EXPIRY])
    assert len(rows) == 42 and set(rows["source"]) == {"breeze"} and rows["r"].notna().all() and rows["model_version"].notna().all()
    atm = rows[(rows["strike"] == 24000)]
    assert atm["iv"].notna().all() and (atm["iv"] - 14.0).abs().max() < 0.6                                   # the mid's IV ≈ the priced vol
    assert rows["mid"].notna().all() and abs(rows["forward"].iloc[0] - 24000) < 5
    deep_itm_call = rows[(rows["strike"] == 23000) & (rows["opt_type"] == "CE")]
    assert deep_itm_call["iv"].isna().all()                                                                  # outside the 3 % ITM band → no IV
    # the second tick appends a new part, never rewrites the first
    intraday.snapshot(store, breeze, ledger, now=TS + timedelta(minutes=15), parquet_root=tmp_path / "chain")
    assert (tmp_path / "chain" / DAY.isoformat() / "part-0001.parquet").exists()
    path = __import__("fo_iv.reads", fromlist=["intraday"]).intraday(store, "NIFTY", day=DAY)
    assert path["source"] == "breeze" and len(path["rows"]) == 4 and path["rows"][0]["atm_iv"] is not None


def test_a_refusing_ledger_stops_the_tick_before_the_sdk_call(store, tmp_path):
    breeze, ledger = FakeBreeze(), FakeLedger(cap=3)
    out = intraday.snapshot(store, breeze, ledger, now=TS, parquet_root=tmp_path / "chain")
    assert out["status"] == "partial" and out["calls"] == 3 and out["refused"] == 1 and len(breeze.calls) == 3
