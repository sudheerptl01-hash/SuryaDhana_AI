"""The intraday OI / IV tape (PLAN 2.1, grown out of the 1.1 pilot; §0.9 / §0.11) and the expiry-day reads (PLAN 2.4).

Rules under test, each with a negative control: never a Breeze call without the ledger, a live session or inside the window;
ICICI's stock codes (BANKNIFTY = CNXBAN — 5 Nov's pilot sent "BANKNIFTY" and stored nothing for it all day); the whole session
09:15–15:30; the cadence plan fits the budget and stretches the lower tiers first; T = clock time to 15:30 IST on the expiry
(an expiry-day series keeps its IV); the tape reads (OI change since the open, max pain, the straddle at the opening strike);
the expiry-day view, the replay rows (UTC-naive ts), the implied-vs-realised scorecard; the NSE v3 fallback only when wired."""
from __future__ import annotations

# ruff: noqa: DTZ001
import math
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
        self.callers: list[str] = []

    def decide(self, caller: str, method: str = "") -> _Decision:
        return _Decision(self.allow, "ok" if self.allow else "day cap reached")

    @contextmanager
    def guard(self, caller: str, method: str = ""):
        if not self.allow or (self.cap is not None and self.acquired >= self.cap):
            raise _Exceeded("cap")
        self.acquired += 1
        self.callers.append(caller)
        yield _Decision(True)


class FakeBreeze:
    """A chain priced at 14 % on a 24,000 forward; ``known`` is the set of ICICI codes it answers (others: no rows)."""

    def __init__(self, known: set[str] | None = None, vol: float = 0.14) -> None:
        self.calls: list[tuple] = []
        self.known, self.vol = known, vol

    def get_option_chain_quotes(self, **kw):
        self.calls.append((kw["stock_code"], kw["expiry_date"], kw["right"]))
        if self.known is not None and kw["stock_code"] not in self.known:
            return {"Success": None, "Status": 500, "Error": "No Data Found"}
        f, t = 24000.0, (EXPIRY - DAY).days / 365
        rows = []
        for k in range(23000, 25001, 100):
            call = kw["right"] == "call"
            px = b76.price(f, k, t, self.vol, call, 0.065)
            rows.append({"strike_price": k, "ltp": round(px, 2), "best_bid_price": round(px * 0.995, 2), "best_offer_price": round(px * 1.005, 2),
                         "best_bid_quantity": "65", "best_offer_quantity": "65", "open_interest": 1000.0, "chnge_oi": 10.0, "total_quantity_traded": "100",
                         "spot_price": "23950.0", "ltt": "05-Nov-2026 10:29:59", "expiry_date": "09-Nov-2026", "right": "Call" if call else "Put"})
        return {"Success": rows, "Status": 200}


@pytest.fixture(autouse=True)
def _fresh_attempts():
    intraday._LAST_ATTEMPT.clear()
    yield
    intraday._LAST_ATTEMPT.clear()


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


def test_the_window_is_the_whole_session_from_0915():
    """M45: the pilot started at 09:20 (and on 5 Nov at 13:35): the tape covers 09:15–15:30 IST."""
    ist = intraday.IST
    assert intraday.in_window(datetime(2026, 11, 6, 9, 15, tzinfo=ist)) and intraday.in_window(datetime(2026, 11, 6, 15, 30, tzinfo=ist))
    assert not intraday.in_window(datetime(2026, 11, 6, 9, 14, tzinfo=ist))                                   # negative control
    assert not intraday.in_window(datetime(2026, 11, 6, 15, 31, tzinfo=ist))


def test_icici_codes_are_used_for_indices_and_stocks(store, tmp_path):
    """M45: BANKNIFTY was OFFLINE all of 5 Nov because the pilot sent stock_code='BANKNIFTY' (ICICI's code is CNXBAN)."""
    assert intraday.breeze_code("BANKNIFTY") == "CNXBAN" and intraday.breeze_code("FINNIFTY") == "NIFFIN"
    assert intraday.breeze_code("NIFTY") == "NIFTY" and intraday.breeze_code("INFY", {"INFY": "INFTEC"}) == "INFTEC"
    assert intraday.breeze_code("ZZZ", {}) == "ZZZ"                                                           # unknown: unchanged
    breeze = FakeBreeze(known={"NIFTY", "CNXBAN"})
    out = intraday.snapshot(store, breeze, FakeLedger(), now=TS, parquet_root=tmp_path / "chain", master={})
    assert {c[0] for c in breeze.calls} == {"NIFTY", "CNXBAN"} and out["empty_legs"] == []
    syms = set(store.read("SELECT DISTINCT symbol FROM iv_intraday")["symbol"])
    assert syms == {"NIFTY", "BANKNIFTY"}
    # negative control: a broker that only knows the NSE spelling stores nothing for BANKNIFTY and says so
    intraday._LAST_ATTEMPT.clear()
    old = FakeBreeze(known={"NIFTY", "BANKNIFTY"})
    out = intraday.snapshot(store, old, FakeLedger(), now=TS + timedelta(minutes=2), parquet_root=tmp_path / "chain", master={})
    assert any("BANKNIFTY(CNXBAN)" in e and "no rows" in e for e in out["empty_legs"])


def test_master_codes_from_the_security_master(tmp_path):
    p = tmp_path / "NSEScripMaster.txt"
    p.write_text('"Token", "ShortName", "Series", "CompanyName", "x", "ExchangeCode"\n'
                 '"1594","INFTEC","EQ","INFOSYS LTD",0.01,"INFY"\n"1462","HDFBAN","W3","HDFC BANK W3",0.01,"HDFCBANK"\n'
                 '"1333","HDFBAN","EQ","HDFC BANK LIMITED",0.01,"HDFCBANK"\n"NIFTY BANK","CNXBAN","0","NIFTY BANK",0.01,"NIFTY BANK"\n')
    codes = intraday.master_codes(p)
    assert codes == {"INFY": "INFTEC", "HDFCBANK": "HDFBAN"}                                                  # index rows and W3 ignored
    assert intraday.master_codes(tmp_path / "missing.txt") == {}


def test_a_tick_writes_parquet_and_iv_rows_from_the_mid(store, tmp_path):
    breeze, ledger = FakeBreeze(), FakeLedger()
    out = intraday.snapshot(store, breeze, ledger, now=TS, parquet_root=tmp_path / "chain")
    assert out["status"] == "ok" and out["calls"] == 8 == ledger.acquired and out["refused"] == 0             # 2 indices × 2 expiries × 2 sides
    assert set(ledger.callers) == {intraday.CALLER}
    assert out["rows"] > 0 and (tmp_path / "chain" / DAY.isoformat() / "part-0000.parquet").exists()
    rows = store.read("SELECT symbol, expiry, strike, opt_type, mid, iv, forward, source, model_version, r FROM iv_intraday WHERE symbol = 'NIFTY' AND expiry = ?", [EXPIRY])
    assert len(rows) == 42 and set(rows["source"]) == {"breeze"} and rows["r"].notna().all()
    assert set(rows["model_version"]) == {intraday.MODEL_VERSION_INTRADAY}
    atm = rows[(rows["strike"] == 24000)]
    assert atm["iv"].notna().all() and (atm["iv"] - 14.0).abs().max() < 0.6                                   # the mid's IV ≈ the priced vol
    assert rows["mid"].notna().all() and abs(rows["forward"].iloc[0] - 24000) < 5
    deep_itm_call = rows[(rows["strike"] == 23000) & (rows["opt_type"] == "CE")]
    assert deep_itm_call["iv"].isna().all()                                                                  # outside the 3 % ITM band → no IV
    # the next tick (2 minutes later) appends a new part, never rewrites the first
    intraday.snapshot(store, breeze, ledger, now=TS + timedelta(minutes=2), parquet_root=tmp_path / "chain")
    assert (tmp_path / "chain" / DAY.isoformat() / "part-0001.parquet").exists()
    path = __import__("fo_iv.reads", fromlist=["intraday"]).intraday(store, "NIFTY", day=DAY)
    assert path["source"] == "breeze" and len(path["rows"]) == 4 and path["rows"][0]["atm_iv"] is not None


def test_a_refusing_ledger_stops_the_tick_before_the_sdk_call(store, tmp_path):
    breeze, ledger = FakeBreeze(), FakeLedger(cap=3)
    out = intraday.snapshot(store, breeze, ledger, now=TS, parquet_root=tmp_path / "chain")
    assert out["status"] == "partial" and out["calls"] == 3 and out["refused"] == 1 and len(breeze.calls) == 3


class _CountingDecision(_Decision):
    def __init__(self, used: int, quota: int | None = None, used_day: int | None = None, cap_day: int | None = None) -> None:
        super().__init__(True)
        self.caller_used_day, self.caller_quota, self.used_day, self.cap_day = used, quota, used_day, cap_day


class CountedLedger(FakeLedger):
    """A ledger whose dry run reports today's counts (the real ledger's caller_used_day / caller_quota / used_day / cap_day)."""

    def __init__(self, used: int, quota: int | None = None, used_day: int | None = None, cap_day: int | None = None) -> None:
        super().__init__()
        self.used, self.quota, self.used_day, self.cap_day = used, quota, used_day, cap_day

    def decide(self, caller: str, method: str = "") -> _Decision:
        return _CountingDecision(self.used, self.quota, self.used_day, self.cap_day)


def test_the_tapes_day_cap_and_the_ledgers_quota_are_enforced(store, tmp_path):
    """The tape's own cap (IV_TAPE_DAY_CAP, default 2,000) and the ledger's quota for iv_intraday: the smaller wins; a tick that
    would cross it is trimmed to whole (call, put) pairs, or skipped."""
    breeze = FakeBreeze()
    out = intraday.snapshot(store, breeze, CountedLedger(1999), now=TS, parquet_root=tmp_path / "chain")
    assert out["status"] == "skipped" and "tape day budget reached (1999/2000" in out["reason"] and breeze.calls == []
    out = intraday.snapshot(store, breeze, CountedLedger(799, quota=800), now=TS, parquet_root=tmp_path / "chain")
    assert out["status"] == "skipped" and "(799/800" in out["reason"] and breeze.calls == []                  # the ledger's quota wins
    out = intraday.snapshot(store, breeze, CountedLedger(1995), now=TS, parquet_root=tmp_path / "chain")      # 5 left: two pairs
    assert out["status"] == "ok" and out["calls"] == 4 and len(breeze.calls) == 4
    intraday._LAST_ATTEMPT.clear()
    out = intraday.snapshot(store, FakeBreeze(), CountedLedger(0, used_day=3_390, cap_day=4_000), now=TS + timedelta(minutes=4),
                            parquet_root=tmp_path / "chain")
    assert out["plan"]["global_left_after_reserve"] == 10 and out["plan"]["rung"] == len(intraday.LADDER) - 1     # the global reserve binds
    assert out["status"] == "skipped" and out.get("quiet")              # the near pair was snapped 4 min ago: at the leanest rung, every 30 min
    # negative control: far below every cap the full tick runs (2 indices × 2 expiries × 2 sides) on the richest plan
    intraday._LAST_ATTEMPT.clear()
    breeze2 = FakeBreeze()
    out = intraday.snapshot(store, breeze2, CountedLedger(10), now=TS + timedelta(minutes=8), parquet_root=tmp_path / "chain")
    assert out["calls"] == 8 and len(breeze2.calls) == 8 and out["plan"]["rung"] == 0
    assert intraday.DEFAULT_DAILY_CAP == 2000


def test_the_cadence_plan_fits_the_budget_and_stretches_the_lower_tiers_first():
    counts = {"index_near": 3, "index_next": 2, "watch_near": 2}
    rich, need, rung = intraday.plan_cadence(counts, 375, 10_000)
    assert rung == 0 and rich == {"index_near": 2, "index_next": 2, "watch_near": 15} and need == 2 * (3 * 188 + 2 * 188 + 2 * 26)
    cad, need, rung = intraday.plan_cadence(counts, 375, 1_500)                     # O-T6's Wave-2 range
    assert cad["index_near"] == 2 and cad["index_next"] > 2 and need <= 1_500
    cad8, need8, _ = intraday.plan_cadence(counts, 375, 800)                        # the ledger's default quota
    assert cad8["index_near"] > 2 and need8 <= 800
    # the near tier never stretches before the next tier has (priority order)
    for r in intraday.LADDER:
        if r["index_near"] and r["index_near"] > 2:
            assert r["index_next"] is None or r["index_next"] >= 15
    # negative control: no budget → the leanest rung, which still needs calls (the tick is then trimmed or skipped)
    lean, need0, rung0 = intraday.plan_cadence(counts, 375, 0)
    assert rung0 == len(intraday.LADDER) - 1 and need0 > 0
    assert intraday.slots_left(375, 2) == 188 and intraday.slots_left(1, 2) == 1 and intraday.slots_left(10, None) == 0


def test_a_tier_is_due_only_once_its_cadence_has_passed(store, tmp_path):
    breeze, ledger = FakeBreeze(), FakeLedger()
    intraday.snapshot(store, breeze, ledger, now=TS, parquet_root=tmp_path / "chain")
    n = len(breeze.calls)
    out = intraday.snapshot(store, breeze, ledger, now=TS + timedelta(seconds=40), parquet_root=tmp_path / "chain")
    assert out["status"] == "skipped" and out.get("quiet") and len(breeze.calls) == n                         # not due: quiet, no call
    out = intraday.snapshot(store, breeze, ledger, now=TS + timedelta(minutes=2), parquet_root=tmp_path / "chain")
    assert out["status"] == "ok" and len(breeze.calls) == 2 * n                                               # negative control: due again


def test_the_next_expiry_is_skipped_when_its_last_eod_was_illiquid(store, tmp_path):
    db.upsert(store, "iv_expiry_daily", pd.DataFrame([{"date": DAY - timedelta(days=1), "symbol": "FINNIFTY", "expiry": e, "dte": 5, "n_iv_strikes": n,
                                                       "model_version": "t", "first_seen_at": TS} for e, n in ((EXPIRY, 76), (EXPIRY + timedelta(days=35), 1))]),
              COLUMNS["iv_expiry_daily"], CASTS["iv_expiry_daily"])
    tg = intraday.tape_targets(store, today=DAY)
    fin = [t for t in tg if t.symbol == "FINNIFTY"]
    assert [t.tier for t in fin] == ["index_near"]
    nif = [t for t in tg if t.symbol == "NIFTY"]
    assert [t.tier for t in nif] == ["index_near", "index_next"]                                              # negative control: liquid next kept
    w = intraday.tape_targets(store, today=DAY, watchlist=["BANKNIFTY", "INFY"])
    assert all(t.tier != "watch_near" or t.symbol == "INFY" for t in w)


def test_time_to_expiry_is_the_clock_to_1530_ist_and_an_expiry_day_keeps_its_iv(store, tmp_path):
    t_close = intraday.t_years(datetime(2026, 11, 5, 10, 0), EXPIRY)               # 15:30 IST on 5 Nov → exactly 4 days
    assert math.isclose(t_close, 4 / 365, rel_tol=1e-9)
    on_day = intraday.t_years(datetime(2026, 11, 9, 4, 0), EXPIRY)                 # 09:30 IST on the expiry day: 6 hours left
    assert math.isclose(on_day, 6 / (24 * 365), rel_tol=1e-9) and intraday.t_years(datetime(2026, 11, 9, 10, 1), EXPIRY) == 0
    # an expiry-day snapshot still derives IVs (the pilot's integer dte was 0 → no rows)
    snap = intraday.Snapshot(ts=datetime(2026, 11, 9, 5, 0), symbol="NIFTY", expiry=EXPIRY)
    t = intraday.t_years(snap.ts, EXPIRY)
    for k in range(23800, 24201, 50):
        for _right, bucket, call in (("CE", snap.calls, True), ("PE", snap.puts, False)):
            px = b76.price(24000.0, k, t, 0.12, call, 0.065)
            bucket.append({"strike": float(k), "bid": px * 0.99, "ask": px * 1.01, "oi": 100.0, "spot": 24000.0})
    rows = intraday.derive(snap, EXPIRY, 0.065, now=snap.ts)
    ivs = [r["iv"] for r in rows if r["strike"] == 24000.0 and r["iv"]]
    assert ivs and abs(ivs[0] - 12.0) < 0.8
    late = intraday.Snapshot(ts=datetime(2026, 11, 9, 10, 0, 30), symbol="NIFTY", expiry=EXPIRY, calls=snap.calls, puts=snap.puts)
    assert intraday.derive(late, EXPIRY, 0.065, now=late.ts) == []                                           # negative control: after 15:30


def _tape_rows(store, ts_list, oi_ce, oi_pe, *, expiry=EXPIRY, fwd=24000.0, mids=None):
    rows = []
    for i, ts in enumerate(ts_list):
        for k in (23900.0, 24000.0, 24100.0):
            for side, oi in (("CE", oi_ce[i]), ("PE", oi_pe[i])):
                mid = (mids or {}).get((i, k, side), 100.0 if k == 24000.0 else 60.0)
                rows.append({"ts": ts, "symbol": "NIFTY", "expiry": expiry, "strike": k, "opt_type": side, "mid": mid, "iv": 14.0 + 0.1 * i,
                             "nse_iv": None, "oi": oi.get(k), "forward": fwd + 10 * i, "spot": fwd + 10 * i, "source": "breeze",
                             "model_version": intraday.MODEL_VERSION_INTRADAY, "r": 0.065, "first_seen_at": ts})
    db.upsert(store, "iv_intraday", pd.DataFrame(rows), COLUMNS["iv_intraday"], CASTS["iv_intraday"])


def test_oi_tape_reads_the_change_since_the_open_max_pain_and_ist_times(store, tmp_path):
    t0 = datetime(2026, 11, 5, 3, 46)                                              # 09:16 IST
    ts = [t0, t0 + timedelta(minutes=2), t0 + timedelta(minutes=4)]
    oi_ce = [{23900.0: 100, 24000.0: 500, 24100.0: 900}, {23900.0: 100, 24000.0: 450, 24100.0: 1000}, {23900.0: 80, 24000.0: 400, 24100.0: 1200}]
    oi_pe = [{23900.0: 900, 24000.0: 500, 24100.0: 100}, {23900.0: 950, 24000.0: 520, 24100.0: 100}, {23900.0: 1000, 24000.0: 600, 24100.0: 90}]
    _tape_rows(store, ts, oi_ce, oi_pe, mids={(2, 24000.0, "CE"): 90.0, (2, 24000.0, "PE"): 95.0})
    out = intraday.oi_tape(store, "NIFTY", day=DAY)
    assert out["expiry"] == EXPIRY.isoformat() and out["snapshots"] == 3 and out["first"] == "09:16" and out["last"] == "09:20"
    assert out["path"][0]["ts"].endswith("+00:00") and out["median_gap_min"] == 2.0
    k = {r["strike"]: r for r in out["strikes"]}
    assert k[24100.0]["ce_chg_open"] == 300 and k[23900.0]["pe_chg_open"] == 100 and k[24000.0]["ce_oi_open"] == 500
    p = out["path"]
    assert p[0]["open_strike"] == 24000.0 and p[-1]["straddle_open_strike"] == 185.0 and p[0]["straddle"] == 200.0
    assert p[-1]["pcr"] == round((1000 + 600 + 90) / (80 + 400 + 1200), 3)
    assert out["frames"][-1]["ce"] == [80, 400, 1200] and out["frames"][0]["ist"] == "09:16"
    assert out["badge"] == "context" and "describes, does not predict" in out["verdict"]
    # negative control: an untouched symbol reads OFFLINE with nothing invented
    empty = intraday.oi_tape(store, "FINNIFTY", day=DAY)
    assert empty["source"] == "OFFLINE" and empty["path"] == [] and empty["strikes"] == []


def test_max_pain_is_the_writers_minimum_payout_strike():
    ce = {100.0: 0.0, 110.0: 50.0, 120.0: 500.0}
    pe = {100.0: 500.0, 110.0: 50.0, 120.0: 0.0}
    assert intraday.max_pain(ce, pe) == 110.0
    assert intraday.max_pain({100.0: 1000.0}, {120.0: 10.0}) == 100.0                 # heavy calls at 100: settling there pays least
    assert intraday.max_pain({}, {}) is None                                         # negative control: no OI, no number


def test_pin_risk_ranks_strikes_near_spot_by_open_interest():
    rows = [{"strike": 24000.0, "ce_oi": 900, "pe_oi": 800}, {"strike": 24050.0, "ce_oi": 100, "pe_oi": 50},
            {"strike": 25000.0, "ce_oi": 9_000, "pe_oi": 9_000}]
    pins = intraday.pin_risk(rows, 24010.0)
    assert [p["strike"] for p in pins] == [24000.0, 24050.0] and pins[0]["distance_pts"] == -10.0            # 25,000 is 4 % away: out
    assert intraday.pin_risk(rows, None) == []


def _seed_scorecard(store):
    expiries = [date(2026, 10, 20), date(2026, 10, 27), date(2026, 11, 3)]
    prior = {date(2026, 10, 20): date(2026, 10, 19), date(2026, 10, 27): date(2026, 10, 26), date(2026, 11, 3): date(2026, 11, 2)}
    settle = {date(2026, 10, 20): 24_300.0, date(2026, 10, 27): 24_020.0, date(2026, 11, 3): 23_500.0}
    ex, surf, idx, summ = [], [], [], []
    for e in expiries:
        p = prior[e]
        ex.append({"date": p, "symbol": "NIFTY", "expiry": e, "dte": (e - p).days, "forward": 24_000.0, "atm_iv": 12.0,
                   "expected_move_pct": 12.0 * math.sqrt((e - p).days / 365), "model_version": "t", "first_seen_at": datetime(2026, 10, 1)})
        for k, ce, pe in ((23_950.0, 160.0, 110.0), (24_000.0, 130.0, 130.0), (24_050.0, 105.0, 155.0)):
            for side, px in (("CE", ce), ("PE", pe)):
                surf.append({"date": p, "symbol": "NIFTY", "expiry": e, "strike": k, "opt_type": side, "price": px, "model_version": "t",
                             "first_seen_at": datetime(2026, 10, 1)})
        idx += [{"symbol": "NIFTY 50", "date": e, "close": settle[e], "source": "nse_daily_file", "first_seen_at": datetime(2026, 10, 1)},
                {"symbol": "NIFTY 50", "date": p, "close": 23_990.0, "source": "nse_daily_file", "first_seen_at": datetime(2026, 10, 1)}]
        summ.append({"date": p, "symbol": "NIFTY", "rv20_cc": 10.0, "model_version": "t", "first_seen_at": datetime(2026, 10, 1)})
    for t, rows in (("iv_expiry_daily", ex), ("iv_surface_daily", surf), ("index_ohlc_daily", idx), ("iv_summary_daily", summ)):
        db.upsert(store, t, pd.DataFrame(rows), COLUMNS[t], CASTS[t])


def test_scorecard_scores_the_last_close_straddle_against_the_settlement(store):
    _seed_scorecard(store)
    sc = intraday.scorecard(store, "NIFTY", before=date(2026, 11, 6))
    rows = {r["expiry"]: r for r in sc["rows"]}
    assert len(rows) == 3 and sc["badge"] == "arithmetic" and "describes, does not predict" in sc["verdict"]
    r = rows["2026-10-20"]
    assert r["strike"] == 24_000.0 and r["straddle"] == 260.0 and r["implied_move_pct"] == round(260 / 24_000 * 100, 3)
    assert r["realised_move_pct"] == round((24_300 / 24_000 - 1) * 100, 3) and r["exceeded"] is True                   # 1.25 % > 1.083 %
    assert rows["2026-10-27"]["exceeded"] is False                                                                      # 0.083 % < 1.083 %
    assert sc["stats"]["n"] == 3 and sc["stats"]["exceeded_pct"] == round(200 / 3, 1) and sc["stats"]["fair_exceeded_pct"] == 42.5
    assert sc["stats"]["compared"] == 3 and 0 <= sc["stats"]["implied_closer"] <= 3
    naive = 10.0 * math.sqrt(1 / 365) * math.sqrt(2 / math.pi)
    assert rows["2026-10-20"]["naive_move_pct"] == round(naive, 3)
    # negative control: a cutoff before the expiries scores nothing; a stock (no index file) is not scored
    assert intraday.scorecard(store, "NIFTY", before=date(2026, 10, 20))["stats"]["n"] == 0
    assert intraday.scorecard(store, "INFY")["rows"] == []


def test_replay_rows_are_utc_naive_and_the_curve_is_normalised_to_the_open(store, tmp_path):
    def bars(start, vals):
        return [{"datetime": f"2026-11-03 {(datetime(2026, 1, 1, 9, 15) + timedelta(minutes=5 * i)).strftime('%H:%M')}:00", "close": v,
                 "open_interest": 1000, "volume": 10} for i, v in enumerate(vals)]
    ce, pe = bars(0, [100, 80, 60]), bars(0, [100, 90, 40])
    rows = intraday.bars_to_rows(ce, pe, symbol="NIFTY", expiry=date(2026, 11, 3), strike=24000.0, spot_open=24010.0, now=TS)
    assert rows[0]["ts"] == datetime(2026, 11, 3, 3, 45) and rows[0]["straddle"] == 200.0                               # 09:15 IST = 03:45 UTC
    intraday.ensure_replay_schema(store)
    db.upsert(store, "iv_expiry_replay", pd.DataFrame(rows), intraday.REPLAY_COLUMNS, intraday.REPLAY_CASTS)
    cur = intraday.replay_curve(store, "NIFTY")
    pts = {p["minute"]: p for p in cur["points"]}
    assert cur["n"] == 1 and pts[0]["median"] == 100.0 and pts[5]["median"] == 85.0 and pts[10]["median"] == 50.0
    assert intraday.replay_curve(store, "NIFTY", before=date(2026, 11, 3))["n"] == 0                                     # negative control
    # one-sided minutes are not stored
    assert len(intraday.bars_to_rows(ce, pe[:1], symbol="NIFTY", expiry=date(2026, 11, 3), strike=24000.0, spot_open=None, now=TS)) == 1


def test_expiry_day_view_on_and_off_an_expiry_day(store, tmp_path):
    _seed_scorecard(store)
    t0 = datetime(2026, 11, 9, 3, 46)
    ts = [t0, t0 + timedelta(minutes=2)]
    _tape_rows(store, ts, [{23900.0: 100, 24000.0: 500, 24100.0: 900}] * 2, [{23900.0: 900, 24000.0: 500, 24100.0: 100}] * 2, expiry=EXPIRY,
               mids={(1, 24000.0, "CE"): 70.0, (1, 24000.0, "PE"): 70.0})
    db.upsert(store, "iv_expiry_daily", pd.DataFrame([{"date": date(2026, 11, 6), "symbol": "NIFTY", "expiry": e, "dte": (e - date(2026, 11, 6)).days,
                                                       "model_version": "t", "first_seen_at": TS} for e in (EXPIRY, EXPIRY + timedelta(days=8))]),
              COLUMNS["iv_expiry_daily"], CASTS["iv_expiry_daily"])
    on = intraday.expiry_day(store, "NIFTY", now=datetime(2026, 11, 9, 3, 50))
    assert on["is_expiry_day"] is True and on["next_expiry"] == (EXPIRY + timedelta(days=8)).isoformat()
    lv = on["live"]
    assert lv["snapshots"] == 2 and lv["open_strike"] == 24000.0 and lv["decay"][-1]["pct_of_open"] == 70.0 and lv["decay"][0]["minute"] == 1
    assert lv["pin_risk"] and lv["pin_risk"][0]["strike"] in (23900.0, 24000.0, 24100.0)
    assert on["scorecard"]["stats"]["n"] == 3 and on["badge"] == "context"
    off = intraday.expiry_day(store, "NIFTY", now=datetime(2026, 11, 6, 4, 0))                                     # Friday: not an expiry
    assert off["is_expiry_day"] is False and off["next_expiry"] == EXPIRY.isoformat() and off["live"] == {"snapshots": 0}
    assert off["last_expiry"] == "2026-11-03"


class _NseChain:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date]] = []

    def __call__(self, symbol: str, expiry: date):
        self.calls.append((symbol, expiry))
        data = []
        for k in range(23800, 24201, 100):
            data.append({"strikePrice": k, "expiryDates": "09-Nov-2026",
                         "CE": {"openInterest": 10, "changeinOpenInterest": 2, "totalTradedVolume": 5, "impliedVolatility": 14.1, "lastPrice": 100,
                                "buyPrice1": 99, "sellPrice1": 101, "underlyingValue": 24000},
                         "PE": {"openInterest": 12, "changeinOpenInterest": -1, "totalTradedVolume": 5, "impliedVolatility": 14.3, "lastPrice": 100,
                                "buyPrice1": 99, "sellPrice1": 101, "underlyingValue": 24000}})
        return {"records": {"timestamp": "05-Nov-2026 10:29:00", "underlyingValue": 24000, "data": data}}


def test_nse_v3_fallback_runs_only_when_wired_and_breeze_is_down(store, tmp_path):
    db.upsert(store, "iv_surface_daily", pd.DataFrame([{"date": DAY - timedelta(days=1), "symbol": "NIFTY", "expiry": EXPIRY, "strike": 24000.0,
                                                        "opt_type": "CE", "lot": 65, "model_version": "t", "first_seen_at": TS}]),
              COLUMNS["iv_surface_daily"], CASTS["iv_surface_daily"])
    nse = _NseChain()
    out = intraday.snapshot(store, None, None, now=TS, parquet_root=tmp_path / "chain", nse_chain=nse)
    assert out["source"] == "nse" and out["calls"] == 0 and {c[0] for c in nse.calls} == {"NIFTY", "BANKNIFTY"}           # near only
    rows = store.read("SELECT oi, nse_iv, source FROM iv_intraday WHERE symbol = 'NIFTY' AND strike = 24000 AND opt_type = 'CE'")
    assert rows["oi"].iloc[0] == 650.0 and rows["nse_iv"].iloc[0] == 14.1 and rows["source"].iloc[0] == "nse"            # contracts × lot
    again = intraday.snapshot(store, None, None, now=TS + timedelta(minutes=2), parquet_root=tmp_path / "chain", nse_chain=nse)
    assert again["status"] == "skipped" and len(nse.calls) == 2                                                        # ≥ 6 min apart
    # negative controls: Breeze live → NSE is never asked; not wired → skipped
    intraday._LAST_ATTEMPT.clear()
    nse2 = _NseChain()
    intraday.snapshot(store, FakeBreeze(), FakeLedger(), now=TS + timedelta(minutes=10), parquet_root=tmp_path / "chain", nse_chain=nse2)
    assert nse2.calls == []
    assert "not wired" in intraday.snapshot(store, None, FakeLedger(), now=TS, parquet_root=tmp_path / "chain")["reason"]


class FakeHist:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_historical_data_v2(self, **kw):
        self.calls.append(kw)
        day = kw["from_date"][:10]
        base = 120.0 if kw["right"] == "call" else 110.0
        return {"Success": [{"datetime": f"{day} {(datetime(2026, 1, 1, 9, 15) + timedelta(minutes=i)).strftime('%H:%M')}:00",
                             "close": base * (1 - i / 400), "open_interest": 1000, "volume": 5} for i in range(0, 376, 15)]}


def test_expiry_replay_backfill_is_metered_resumable_and_refuses_the_windows(store, tmp_path):
    db.upsert(store, "iv_expiry_daily", pd.DataFrame([{"date": e - timedelta(days=1), "symbol": "NIFTY", "expiry": e, "dte": 1, "model_version": "t",
                                                       "first_seen_at": TS} for e in (date(2026, 10, 27), date(2026, 11, 3))]),
              COLUMNS["iv_expiry_daily"], CASTS["iv_expiry_daily"])
    db.upsert(store, "index_ohlc_daily", pd.DataFrame([{"symbol": "NIFTY 50", "date": e, "open": 24_012.0, "close": 24_100.0, "source": "nse_daily_file",
                                                        "first_seen_at": TS} for e in (date(2026, 10, 27), date(2026, 11, 3))]),
              COLUMNS["index_ohlc_daily"], CASTS["index_ohlc_daily"])
    hist, ledger = FakeHist(), FakeLedger()
    evening = datetime(2026, 11, 6, 11, 30)                                                       # 17:00 IST Friday
    inside = intraday.run_expiry_replay(store, hist, ledger, now=datetime(2026, 11, 6, 14, 0), sleep=lambda s: None)      # 19:30 IST
    assert inside["status"] == "skipped" and "inside 18:30" in inside["reason"] and hist.calls == []
    out = intraday.run_expiry_replay(store, hist, ledger, now=evening, since=date(2026, 10, 1), sleep=lambda s: None)
    assert out["status"] == "ok" and out["calls"] == 4 and out["expiries"] == {"NIFTY": 2} and set(ledger.callers) == {intraday.REPLAY_CALLER}
    assert {c["strike_price"] for c in hist.calls} == {"24000"} and {c["stock_code"] for c in hist.calls} == {"NIFTY"}
    again = intraday.run_expiry_replay(store, hist, ledger, now=evening, since=date(2026, 10, 1), sleep=lambda s: None)
    assert again["calls"] == 0 and len(hist.calls) == 4                                                                # resumable
    assert intraday.run_expiry_replay(store, hist, None, now=evening)["status"] == "skipped"                          # never unmetered


def test_a_refused_replay_call_ends_the_whole_run(store, tmp_path):
    for sym, name in (("NIFTY", "NIFTY 50"), ("BANKNIFTY", "NIFTY BANK")):
        db.upsert(store, "iv_expiry_daily", pd.DataFrame([{"date": date(2026, 11, 2), "symbol": sym, "expiry": date(2026, 11, 3), "dte": 1,
                                                           "model_version": "t", "first_seen_at": TS}]), COLUMNS["iv_expiry_daily"], CASTS["iv_expiry_daily"])
        db.upsert(store, "index_ohlc_daily", pd.DataFrame([{"symbol": name, "date": date(2026, 11, 3), "open": 24_000.0, "close": 24_100.0,
                                                            "source": "nse_daily_file", "first_seen_at": TS}]), COLUMNS["index_ohlc_daily"], CASTS["index_ohlc_daily"])
    hist, ledger = FakeHist(), FakeLedger(cap=1)
    out = intraday.run_expiry_replay(store, hist, ledger, symbols=("NIFTY", "BANKNIFTY"), now=datetime(2026, 11, 6, 11, 30), since=date(2026, 10, 1),
                                     sleep=lambda s: None)
    assert len(hist.calls) == 1 and any("budget refused" in e for e in out["errors"]) and out["expiries"] == {}
    # negative control: with budget, both symbols replay (2 calls each)
    hist2 = FakeHist()
    out2 = intraday.run_expiry_replay(store, hist2, FakeLedger(), symbols=("NIFTY", "BANKNIFTY"), now=datetime(2026, 11, 6, 11, 30),
                                      since=date(2026, 10, 1), sleep=lambda s: None)
    assert len(hist2.calls) == 4 and out2["expiries"] == {"NIFTY": 1, "BANKNIFTY": 1}
    assert {c["stock_code"] for c in hist2.calls} == {"NIFTY", "CNXBAN"} and {c["strike_price"] for c in hist2.calls} == {"24000"}


def test_the_tape_joins_the_latest_raw_part_for_bid_ask_and_the_change_vs_the_previous_session(store, tmp_path):
    t0 = datetime(2026, 11, 5, 3, 46)
    _tape_rows(store, [t0, t0 + timedelta(minutes=2)], [{23900.0: 1, 24000.0: 2, 24100.0: 3}] * 2, [{23900.0: 3, 24000.0: 2, 24100.0: 1}] * 2)
    raw = [{"ts": t0 + timedelta(minutes=2), "symbol": "NIFTY", "expiry": EXPIRY, "right": side, "strike": k, "bid": 99.0, "ask": 101.0,
            "chnge_oi": -500.0 if side == "CE" else 700.0, "source": "breeze"} for k in (23900.0, 24000.0, 24100.0) for side in ("CE", "PE")]
    intraday.write_parquet_part(tmp_path / "chain", DAY, raw)
    out = intraday.oi_tape(store, "NIFTY", day=DAY, parquet_root=tmp_path / "chain")
    k = {r["strike"]: r for r in out["strikes"]}
    assert k[24000.0]["ce_bid"] == 99.0 and k[24000.0]["pe_ask"] == 101.0 and k[24000.0]["ce_chg_prev"] == -500.0 and k[24000.0]["pe_chg_prev"] == 700.0
    # negative control: without the raw store the bid / ask are unknown, never invented
    bare = intraday.oi_tape(store, "NIFTY", day=DAY, parquet_root=None)
    assert all(r["ce_bid"] is None and r["pe_chg_prev"] is None for r in bare["strikes"])


def test_expiry_day_compares_today_with_the_replayed_curve_at_the_same_minute(store, tmp_path):
    t0 = datetime(2026, 11, 9, 3, 46)                                             # 09:16 IST on the expiry day
    _tape_rows(store, [t0, t0 + timedelta(minutes=60)], [{23900.0: 1, 24000.0: 2, 24100.0: 3}] * 2, [{23900.0: 3, 24000.0: 2, 24100.0: 1}] * 2,
               mids={(1, 24000.0, "CE"): 50.0, (1, 24000.0, "PE"): 50.0})
    db.upsert(store, "iv_expiry_daily", pd.DataFrame([{"date": date(2026, 11, 6), "symbol": "NIFTY", "expiry": EXPIRY, "dte": 3, "model_version": "t",
                                                       "first_seen_at": TS}]), COLUMNS["iv_expiry_daily"], CASTS["iv_expiry_daily"])
    intraday.ensure_replay_schema(store)
    bars = [{"datetime": f"2026-11-03 {(datetime(2026, 1, 1, 9, 15) + timedelta(minutes=m)).strftime('%H:%M')}:00", "close": 100 - m / 5}
            for m in range(0, 376, 5)]
    db.upsert(store, "iv_expiry_replay", pd.DataFrame(intraday.bars_to_rows(bars, bars, symbol="NIFTY", expiry=date(2026, 11, 3), strike=24000.0,
                                                                            spot_open=None, now=TS)), intraday.REPLAY_COLUMNS, intraday.REPLAY_CASTS)
    out = intraday.expiry_day(store, "NIFTY", now=datetime(2026, 11, 9, 4, 50))
    v = out["live"]["vs_curve"]
    assert out["is_expiry_day"] and out["curve"]["n"] == 1 and v["today_pct"] == 50.0 and v["minute"] == 61
    assert abs(v["median_pct"] - (100 - 60 / 5) / 100 * 100) < 1.5                                                     # the curve at ≈ 10:16
    # negative control: the replay of the day itself is never its own reference (before=today)
    assert intraday.replay_curve(store, "NIFTY", before=date(2026, 11, 3))["n"] == 0


FIXTURES = ROOT / "tests" / "fixtures" / "expiry_replay"


def test_the_replay_curve_from_real_breeze_fixtures(store):
    """Fixtures: Breeze get_historical_data_v2 1-minute bars of the ATM call + put on three past expiry days (fetched 6 Nov 2026
    09:21 IST through the budget ledger, 6 calls). The fixed-strike straddle is not a pure decay: 3 Nov's +2 % rally lifted the
    23,600 straddle to its intrinsic value (1.39× the open) while 27 Oct's quiet session left 0.27× — the curve keeps both."""
    import json

    intraday.ensure_replay_schema(store)
    for f in sorted(FIXTURES.glob("*.json")):
        d = json.loads(f.read_text())
        rows = intraday.bars_to_rows(d["ce"], d["pe"], symbol=d["symbol"], expiry=date.fromisoformat(d["expiry"]), strike=float(d["strike"]),
                                     spot_open=None, now=TS)
        assert len(rows) == 376 and rows[0]["ts"].hour == 3 and rows[0]["ts"].minute == 45                          # 09:15 IST, UTC-naive
        db.upsert(store, "iv_expiry_replay", pd.DataFrame(rows), intraday.REPLAY_COLUMNS, intraday.REPLAY_CASTS)
    nifty = intraday.replay_curve(store, "NIFTY")
    pts = {p["minute"]: p for p in nifty["points"]}
    assert nifty["n"] == 2 and nifty["expiries"] == ["2026-10-27", "2026-11-03"] and pts[0]["median"] == 100.0
    close = pts[375]
    lo, hi = 27.43, 138.59                                                   # 27 Oct 0.27×, 3 Nov 1.39× (linear percentiles of two days)
    assert close["n"] == 2 and abs(close["median"] - (lo + hi) / 2) < 1.0 and abs(close["p25"] - (lo + 0.25 * (hi - lo))) < 1.0 and close["p75"] > 100
    bank = intraday.replay_curve(store, "BANKNIFTY")                                                                    # negative control
    assert bank["n"] == 1 and abs({p["minute"]: p for p in bank["points"]}[375]["median"] - 92.4) < 0.6


def test_a_late_tape_is_compared_with_the_curve_rebased_to_its_first_snapshot(store):
    intraday.ensure_replay_schema(store)
    bars = [{"datetime": f"2026-11-03 {(datetime(2026, 1, 1, 9, 15) + timedelta(minutes=m)).strftime('%H:%M')}:00", "close": 100 - m / 5}
            for m in range(0, 376, 5)]
    db.upsert(store, "iv_expiry_replay", pd.DataFrame(intraday.bars_to_rows(bars, bars, symbol="NIFTY", expiry=date(2026, 11, 3), strike=24000.0,
                                                                            spot_open=None, now=TS)), intraday.REPLAY_COLUMNS, intraday.REPLAY_CASTS)
    late = intraday.replay_curve(store, "NIFTY", start_minute=260)                  # today's first snapshot 13:35
    pts = {p["minute"]: p for p in late["points"]}
    assert min(pts) == 260 and pts[260]["median"] == 100.0 and "13:35" in late["note"]
    assert abs(pts[300]["median"] - (100 - 300 / 5) / (100 - 260 / 5) * 100) < 0.5                        # 40 / 48 of the 13:35 value
    whole = intraday.replay_curve(store, "NIFTY")                                    # negative control: from 09:15
    assert min(p["minute"] for p in whole["points"]) == 0 and abs({p["minute"]: p for p in whole["points"]}[300]["median"] - 40.0) < 0.5
