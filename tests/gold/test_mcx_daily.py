"""O-8 (6 Nov 2026): the ICICI Breeze daily history of MCX gold futures — OHLC + volume + OI per LIVE expiry into its own
table ``gold_mcx_daily`` (``gold/mcx_daily.py``, group ``breeze_daily``, ``GET /db/gold/mcx/daily``). Every rule with a
negative control:

* one row per session per live contract, OI included, from recorded-shape Breeze payloads (numbers as strings, ISO T/Z
  stamps); the request arguments and the budget-ledger caller;
* an expired contract is never fetched (one expiring ON the session still is);
* today's partial bar is skipped before the close and stored after it;
* a budget refusal stops the run before the SDK runs and reports the rest; no session → ``no_session``; a failed call
  (``Status != 200`` or an ``Error`` field) is reported with its message and three in a row stop the run;
* the per-run cap reports leftovers, which lead the next run; calls are ≥ 1.2 s apart;
* re-runs are idempotent (no duplicate rows, ``first_seen_at`` never moves; a changed bar is a revision);
* ``gold_curve`` is untouched (its readers filter ``exchange = 'MCX'`` without a source);
* ``/db/gold/mcx/daily`` serves the rows with ISO dates and ``+00:00`` timestamps.

No network, no Breeze, no ledger file: the SDK is a fake and the ledger a recording stub."""
from __future__ import annotations

# ruff: noqa: DTZ001
# (timestamps are UTC-naive by the store's convention)
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import pytest
from _support import FakeHttp, FakeResponse
from gold import api as gold_api
from gold import catalog_seed, db, ingest_india, jobs, mcx_close, mcx_daily, reads, schema

THU, FRI = date(2026, 11, 5), date(2026, 11, 6)
DEC, FEB, APR = date(2026, 12, 4), date(2027, 2, 5), date(2027, 4, 5)
M_EXPIRED, M_TODAY, M_DEC = date(2026, 11, 4), date(2026, 11, 5), date(2026, 12, 4)     # GOLDM months on the Thu master
FRI_0935 = datetime(2026, 11, 6, 4, 5)           # 09:35 IST Fri 6 Nov (UTC-naive): the latest completed session is Thu
SAT_0030 = datetime(2026, 11, 6, 19, 0)          # 00:30 IST Sat 7 Nov: Fri's 23:55 close has passed
MON_0935 = datetime(2026, 11, 9, 4, 5)


# ── fakes ──────────────────────────────────────────────────────────────────────────────────────────────────────

class Ledger:
    """The budget ledger's ``guard`` contract: refuses (BudgetExceeded, BEFORE the SDK runs) after ``allow`` calls."""

    def __init__(self, allow: int | None = None) -> None:
        self.allow, self.calls = allow, []

    @contextmanager
    def guard(self, caller: str, method: str = ""):
        from shared import breeze_budget

        if self.allow is not None and len(self.calls) >= self.allow:
            raise breeze_budget.BudgetExceeded(breeze_budget.Decision(False, "day cap reached", caller, method, 0, 4000, 0, 60, 4000,
                                                                      None, 1.0))
        self.calls.append((caller, method))
        yield None


@pytest.fixture(autouse=True)
def ledger(monkeypatch):
    from shared import breeze_budget

    lg = Ledger()
    monkeypatch.setattr(breeze_budget, "ledger", lambda: lg)
    return lg


BASE = {"GOLD": 139000.0, "GOLDMI": 138500.0}


def bar(stock: str, expiry: date, d: date, *, stamp: str | None = None, as_strings: bool = False, oi: int | None = None) -> dict:
    """One row in the shape Breeze v2 returns for daily futures bars (reports/breeze_catalog/INFY/samples/hist_future_1day.json),
    on MCX: close/datetime/exchange_code/expiry_date/high/low/open/open_interest/product_type/stock_code/volume."""
    c = BASE[stock] + (expiry - DEC).days + (d.toordinal() % 7) * 10.0
    row: dict[str, Any] = {"close": c, "datetime": stamp or f"{d.isoformat()} 00:00:00", "exchange_code": "MCX",
                           "expiry_date": f"{expiry:%d-%b-%Y}".upper(), "high": c + 400.0, "low": c - 300.0, "open": c - 100.0,
                           "open_interest": oi if oi is not None else 10000 + d.day, "product_type": "Futures", "stock_code": stock,
                           "volume": 5000 + d.day}
    if as_strings:
        row.update({k: str(row[k]) for k in ("close", "high", "low", "open", "open_interest", "volume")})
    return row


class FakeBreeze:
    """get_historical_data_v2 → a weekday bar for every day in [from_date, to_date] (today's partial one included, as a
    to_date of today asks for). ``answers[(stock, expiry)]`` overrides the whole reply; ``oi_override`` one bar's OI."""

    def __init__(self, answers: dict[tuple[str, date], Any] | None = None, oi_override: dict[tuple[str, date, date], int] | None = None):
        self.answers, self.oi_override, self.calls = answers or {}, oi_override or {}, []

    def get_historical_data_v2(self, **kw):
        self.calls.append(kw)
        exp = date.fromisoformat(kw["expiry_date"][:10])
        if (kw["stock_code"], exp) in self.answers:
            return self.answers[(kw["stock_code"], exp)]
        d, end, rows = date.fromisoformat(kw["from_date"][:10]), date.fromisoformat(kw["to_date"][:10]), []
        while d <= end:
            if d.weekday() < 5 and d <= exp:
                if (kw["stock_code"], exp, d) == ("GOLD", DEC, THU):          # numbers as strings
                    rows.append(bar("GOLD", exp, d, as_strings=True, oi=self.oi_override.get(("GOLD", exp, d))))
                elif (kw["stock_code"], exp, d) == ("GOLD", DEC, THU - timedelta(days=1)):       # an ISO stamp with T/Z
                    rows.append(bar("GOLD", exp, d, stamp=f"{d.isoformat()}T00:00:00.000Z"))
                else:
                    rows.append(bar(kw["stock_code"], exp, d, oi=self.oi_override.get((kw["stock_code"], exp, d))))
            d += timedelta(days=1)
        return {"Error": None, "Status": 200, "Success": rows}


def _master(trade_date: date, symbol: str, expiry: date, oi: int) -> dict:
    rel = datetime.combine(trade_date + timedelta(days=1), datetime.min.time()) + timedelta(hours=2)   # 07:30 IST next day
    return {"trade_date": trade_date, "exchange": "MCX", "symbol": symbol, "expiry": expiry, "settle": 139452.0, "band_lo": 135269.0,
            "band_hi": 143635.0, "open_interest": oi, "unit": "INR/10g", "source": "icici_master_band", "quality": "proxy",
            "session_date": ingest_india.band_session(trade_date), "release_at": rel, "first_seen_at": rel}


@pytest.fixture
def masters(store):
    """The Fri 07:35 ICICI master (OI session Thu 5 Nov): GOLD DEC / FEB live (APR OI 0 → not picked), GOLDM listing a
    month that expired Wed 4 Nov (a stale line), one expiring Thu 5 Nov (its last day) and DEC."""
    db.upsert(store, "gold_curve", pd.DataFrame([
        _master(THU, "GOLD", DEC, 16110), _master(THU, "GOLD", FEB, 1180), _master(THU, "GOLD", APR, 0),
        _master(THU, "GOLDM", M_EXPIRED, 40), _master(THU, "GOLDM", M_TODAY, 300), _master(THU, "GOLDM", M_DEC, 9000)]))
    return store


def _run(store, fake, now=FRI_0935, **kw):
    kw.setdefault("sleep", lambda s: None)
    return mcx_daily.run(store, (lambda: fake) if fake is not None else None, now=now, **kw)


def _rows(store) -> pd.DataFrame:
    return db.query_df(store, "SELECT * FROM gold_mcx_daily ORDER BY family, expiry, trade_date")


def _fetched(fake) -> list[tuple[str, str]]:
    return [(c["stock_code"], c["expiry_date"][:10]) for c in fake.calls]


def _one(store, family: str, expiry: date, day: date) -> pd.Series:
    df = db.query_df(store, "SELECT * FROM gold_mcx_daily WHERE family = ? AND expiry = ? AND trade_date = ?", [family, expiry, day])
    assert len(df) == 1, (family, expiry, day, len(df))
    return df.iloc[0]


# ── storage per live contract ────────────────────────────────────────────────────────────────────────────────────

def test_stores_one_row_per_session_per_live_contract_with_oi(masters, ledger):
    fake = FakeBreeze()
    res = _run(masters, fake)
    assert res["status"] == "ok" and res["session"] == "2026-11-05" and res["planned"] == 4 and res["breeze_calls"] == 4
    # fronts first (GOLD, then GOLDM), then the second months; GOLDM's code is GOLDMI (mcx_close.BREEZE_CODE)
    assert _fetched(fake) == [("GOLD", "2026-12-04"), ("GOLDMI", "2026-11-05"), ("GOLD", "2027-02-05"), ("GOLDMI", "2026-12-04")]
    kw = fake.calls[0]
    assert {k: kw[k] for k in ("interval", "exchange_code", "product_type", "right", "strike_price")} == {
        "interval": "1day", "exchange_code": "MCX", "product_type": "futures", "right": "others", "strike_price": "0"}
    # first fetch: 180 days back; to today (the partial bar is filtered, not avoided)
    assert (kw["from_date"], kw["to_date"], kw["expiry_date"]) == ("2026-05-09T00:00:00.000Z", "2026-11-06T23:59:00.000Z",
                                                                    "2026-12-04T06:00:00.000Z")
    assert ledger.calls == [("data-service.gold_breeze_daily", "get_historical_data_v2")] * 4
    rows = _rows(masters)
    per = rows.groupby(["family", "expiry"])["trade_date"].agg(["count", "max"])
    assert {(f, db.to_date(e)) for f, e in per.index} == {("GOLD", DEC), ("GOLD", FEB), ("GOLDM", M_TODAY), ("GOLDM", M_DEC)}
    assert all(db.to_date(m) == THU for m in per["max"])
    assert int(db.scalar(masters, "SELECT COUNT(*) FROM (SELECT DISTINCT trade_date, family, expiry FROM gold_mcx_daily)")) == len(rows)
    thu = _one(masters, "GOLD", DEC, THU)
    exp = bar("GOLD", DEC, THU)                                      # the same bar as numbers: the strings parsed to these
    assert (thu["open"], thu["high"], thu["low"], thu["close"], thu["volume"], thu["open_interest"]) == (
        exp["open"], exp["high"], exp["low"], exp["close"], exp["volume"], exp["open_interest"])
    assert int(_one(masters, "GOLD", DEC, THU - timedelta(days=1))["open_interest"]) == 10004   # the T/Z stamp is Wed 4 Nov, not Tue
    assert set(rows["source"]) == {"breeze_daily"} and set(rows["quality"]) == {"broker"}
    assert (rows["release_at"] == pd.Timestamp(FRI_0935)).all() and (rows["first_seen_at"] == pd.Timestamp(FRI_0935)).all()
    assert rows["open_interest"].notna().all() and res["inserted"] == res["new"] == len(rows)
    assert res["payload_keys"] == sorted(bar("GOLD", DEC, THU))                     # key names only, never values


def test_an_expired_contract_is_never_fetched(masters, monkeypatch):
    # control: the stale master line exists
    assert db.scalar(masters, "SELECT COUNT(*) FROM gold_curve WHERE symbol = 'GOLDM' AND expiry = ?", [M_EXPIRED]) == 1
    fake = FakeBreeze()
    _run(masters, fake, families=["GOLDM"])
    assert ("GOLDMI", "2026-11-04") not in _fetched(fake)
    assert ("GOLDMI", "2026-11-05") in _fetched(fake)                    # negative control: expiring ON the session is live
    assert db.scalar(masters, "SELECT COUNT(*) FROM gold_mcx_daily WHERE expiry = ?", [M_EXPIRED]) == 0
    assert [c[:2] for c in mcx_daily.live_contracts(masters, THU, families=["GOLDM"])] == [("GOLDM", M_TODAY), ("GOLDM", M_DEC)]
    # the rule itself: an expired contract is dropped even when the picker hands one over; the ranks restart from it
    monkeypatch.setattr(mcx_close, "contracts_for", lambda *a, **k: [("GOLDM", M_EXPIRED), ("GOLDM", M_TODAY), ("GOLDM", M_DEC)])
    assert mcx_daily.live_contracts(masters, THU) == [("GOLDM", M_TODAY, 0), ("GOLDM", M_DEC, 1)]
    assert mcx_daily.live_contracts(masters, M_EXPIRED)[0] == ("GOLDM", M_EXPIRED, 0)      # control: live on its own last day


def test_todays_partial_bar_is_skipped_before_the_close_and_stored_after(masters):
    fake = FakeBreeze()
    res = _run(masters, fake, families=["GOLD"])
    assert all(c["skipped_partial"] == ["2026-11-06"] for c in res["contracts"])
    assert db.scalar(masters, "SELECT COUNT(*) FROM gold_mcx_daily WHERE trade_date = ?", [FRI]) == 0
    # negative control: after Friday's 23:55 close (+2 min) the same bar is complete and stored
    res = _run(masters, fake, now=SAT_0030, families=["GOLD"])
    assert res["session"] == "2026-11-06" and all(c["skipped_partial"] == [] for c in res["contracts"])
    assert db.scalar(masters, "SELECT COUNT(*) FROM gold_mcx_daily WHERE trade_date = ?", [FRI]) == 2       # DEC + FEB


# ── budget, session, failures, cap, pacing ───────────────────────────────────────────────────────────────────────

def test_a_budget_refusal_stops_the_run_before_the_sdk_and_reports_the_rest(masters, ledger):
    ledger.allow = 1
    fake = FakeBreeze()
    res = _run(masters, fake)
    assert res["status"] == "budget" and res["breeze_calls"] == 1 and len(fake.calls) == 1              # refused BEFORE the SDK
    assert [(n["family"], n["expiry"], n["reason"]) for n in res["not_fetched"]] == [
        ("GOLDM", "2026-11-05", "budget"), ("GOLD", "2027-02-05", "budget"), ("GOLDM", "2026-12-04", "budget")]
    assert res["contracts"][-1]["status"] == "budget" and "day cap" in res["contracts"][-1]["reason"]
    assert set(_rows(masters)["expiry"].map(db.to_date)) == {DEC}                                         # only the call that ran
    # negative control: with budget the same run fetches every contract
    ledger.allow, ledger.calls = None, []
    assert _run(masters, FakeBreeze())["not_fetched"] == []


def test_no_session_is_reported_and_stores_nothing(masters):
    res = _run(masters, None)
    assert res["status"] == "no_session" and res["inserted"] == 0 and res["breeze_calls"] == 0 and "Breeze session" in res["reason"]
    assert len(res["not_fetched"]) == 4 and {n["reason"] for n in res["not_fetched"]} == {"no_session"}

    def broken():
        raise RuntimeError("session getter failed")

    assert mcx_daily.run(masters, broken, now=FRI_0935)["status"] == "no_session"
    assert mcx_daily.run(masters, lambda: None, now=FRI_0935)["status"] == "no_session"
    assert _rows(masters).empty
    # negative control: with a session the group stores rows (through the job registry, the getter is ctx.breeze)
    fake = FakeBreeze()
    out = jobs.run_job(masters, None, "gold_breeze_daily", ["breeze_daily"], now=FRI_0935, breeze=lambda: fake, params={"families": ["GOLD"]})
    g = out["groups"]["breeze_daily"]
    assert g["status"] == "ok" and g["inserted"] > 0 and out["rows_total"] == g["inserted"]               # counted once
    assert out["tables"]["gold_mcx_daily"]["rows"] == g["inserted"] and out["tables"]["gold_mcx_daily"]["last"] == "2026-11-05"
    assert jobs.run_job(masters, None, "x", ["breeze_daily"], now=FRI_0935)["groups"]["breeze_daily"]["status"] == "no_session"


def test_a_failed_call_is_reported_with_its_message_and_three_in_a_row_stop_the_run(masters):
    fake = FakeBreeze(answers={("GOLD", FEB): {"Status": 500, "Error": "Internal Server Error", "Success": None}})
    res = _run(masters, fake)
    feb = next(c for c in res["contracts"] if c["expiry"] == "2027-02-05")
    assert feb["status"] == "error" and "500" in feb["error"] and "Internal Server Error" in feb["error"]
    assert res["status"] == "ok" and len(fake.calls) == 4                                 # one failure never stops the others
    assert db.scalar(masters, "SELECT COUNT(*) FROM gold_mcx_daily WHERE expiry = ?", [FEB]) == 0
    # an Error field on a 200, a non-list body, a non-dict body: each a failed call; three in a row → degraded, the rest
    # reported (order: FEB, never stored, first; then the fronts DEC and GOLDM Nov; GOLDM Dec is left)
    bad = {("GOLD", DEC): {"Status": 200, "Error": "Invalid expiry", "Success": None},
           ("GOLDMI", M_TODAY): {"Status": 200, "Error": None, "Success": "no data"}, ("GOLD", FEB): "<html>"}
    fake = FakeBreeze(answers=bad)
    res = _run(masters, fake)
    assert res["status"] == "degraded" and len(fake.calls) == 3 and [c["status"] for c in res["contracts"]] == ["error"] * 3
    errors = {c["expiry"] + " " + c["family"]: c["error"] for c in res["contracts"]}
    assert "not a JSON object" in errors["2027-02-05 GOLD"] and "Invalid expiry" in errors["2026-12-04 GOLD"]
    assert "not a list" in errors["2026-11-05 GOLDM"]
    assert res["not_fetched"] == [{"family": "GOLDM", "expiry": "2026-12-04", "rank": 1, "reason": "degraded"}]
    # negative control: an empty answer is not a failure (a new month with no bar yet)
    fake = FakeBreeze(answers={("GOLD", DEC): {"Status": 200, "Error": None, "Success": []}})
    dec = next(c for c in _run(masters, fake, families=["GOLD"])["contracts"] if c["expiry"] == "2026-12-04")
    assert dec["status"] == "ok" and dec["bars"] == 0


def test_the_cap_reports_leftovers_which_lead_the_next_run(masters):
    fake = FakeBreeze()
    res = _run(masters, fake, max_calls=2)
    assert res["status"] == "capped" and res["breeze_calls"] == 2
    assert [(n["family"], n["expiry"], n["reason"]) for n in res["not_fetched"]] == [("GOLD", "2027-02-05", "capped"),
                                                                                    ("GOLDM", "2026-12-04", "capped")]
    fake2 = FakeBreeze()
    res = _run(masters, fake2, max_calls=2)                                  # the never-stored leftovers go first
    assert _fetched(fake2) == [("GOLD", "2027-02-05"), ("GOLDMI", "2026-12-04")] and res["status"] == "capped"
    assert {(f, db.to_date(e)) for f, e in _rows(masters)[["family", "expiry"]].drop_duplicates().itertuples(index=False)} == {
        ("GOLD", DEC), ("GOLD", FEB), ("GOLDM", M_TODAY), ("GOLDM", M_DEC)}
    # negative control: the default cap (15) covers every live contract of a normal day
    assert mcx_daily.MAX_CALLS == 15 and _run(masters, FakeBreeze())["status"] == "ok"


def test_calls_are_at_least_1_2_s_apart(masters):
    slept: list[float] = []
    _run(masters, FakeBreeze(), sleep=slept.append)
    assert slept == [mcx_daily.PACE_S] * 3 and mcx_daily.PACE_S >= 1.2                  # none before the first call
    assert mcx_daily.MIN_PACE_S == 1.2


# ── idempotency and the window ───────────────────────────────────────────────────────────────────────────────────

def test_a_rerun_is_idempotent_and_a_changed_bar_is_a_revision_that_keeps_first_seen(masters):
    first = _run(masters, FakeBreeze())
    n = len(_rows(masters))
    later = FRI_0935 + timedelta(hours=2)
    fake = FakeBreeze()
    again = _run(masters, fake, now=later)
    assert (again["inserted"], again["new"], again["revised"]) == (0, 0, 0) and again["unchanged"] > 0
    assert len(_rows(masters)) == n == first["new"]                                    # no duplicate rows
    assert (_rows(masters)["release_at"] == pd.Timestamp(FRI_0935)).all()             # nothing re-stamped
    # a stored contract re-reads its last 10 sessions (Fri 23 Oct … Thu 5 Nov), not 180 days
    assert {c["from_date"][:10] for c in fake.calls} == {"2026-10-23"}
    # Breeze corrects Thursday's OI: one revision, release_at = that fetch, first_seen_at kept
    fix = FakeBreeze(oi_override={("GOLD", DEC, THU): 16110})
    rev = _run(masters, fix, now=later + timedelta(hours=1))
    assert (rev["new"], rev["revised"], rev["inserted"]) == (0, 1, 1) and len(_rows(masters)) == n
    row = _one(masters, "GOLD", DEC, THU)
    assert int(row["open_interest"]) == 16110 and row["first_seen_at"] == pd.Timestamp(FRI_0935)
    assert row["release_at"] == pd.Timestamp(later + timedelta(hours=1))
    # control: every other bar kept its first fetch as release_at
    assert db.scalar(masters, """SELECT COUNT(*) FROM gold_mcx_daily WHERE release_at <> ?""", [FRI_0935]) == 1


def test_window_start_rules():
    last = THU
    assert mcx_daily.window_start(None, last, None) == last - timedelta(days=180)          # never stored: 180 days
    assert mcx_daily.window_start(None, last, date(2026, 1, 2)) == date(2026, 1, 2)        # never stored: backfill_from
    assert mcx_daily.window_start(date(2026, 11, 4), last, None) == date(2026, 10, 23)     # stored: the last 10 sessions
    assert mcx_daily.window_start(date(2026, 10, 1), last, None) == date(2026, 10, 1)      # a gap after downtime closes
    assert mcx_daily.window_start(date(2026, 11, 4), last, date(2026, 9, 1)) == date(2026, 9, 1)   # an explicit backfill wins
    assert mcx_daily.window_start(date(2026, 11, 4), last, date(2026, 11, 3)) == date(2026, 10, 23)  # a later one does not


# ── parsing ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("2026-11-05 00:00:00", THU), ("2026-11-05T00:00:00.000Z", THU), ("2026-11-05T00:00:00Z", THU), ("2026-11-05", THU),
    ("2026-11-04T18:30:00.000Z", THU),             # a true UTC instant of IST midnight is still Thursday's bar
    ("2026-11-05T00:00:00+05:30", THU), ("05-11-2026 00:00:00", THU), ("05-Nov-2026", THU), ("04-DEC-2026", DEC),
    ("", None), (None, None), ("junk", None), ("2026-13-45 00:00:00", None),
])
def test_parse_day(raw, expected):
    assert mcx_daily.parse_day(raw) == expected


def test_parse_rows_is_defensive():
    rows = [bar("GOLD", DEC, THU, as_strings=True),
            {"datetime": "2026-11-04 00:00:00", "close": "", "open": "-", "high": None, "low": "abc", "open_interest": "16,282",
             "volume": None},                                              # no price but an OI: kept, prices None
            {"datetime": "2026-11-03 00:00:00", "close": 0, "open": 0, "high": 0, "low": 0},          # nothing at all: dropped
            {**bar("GOLD", FEB, THU), "datetime": "2026-11-02 00:00:00"},                             # another contract: dropped
            {"close": 1.0},                                                                            # no date: dropped
            "not a row"]
    bars, dropped = mcx_daily.parse_rows(rows, DEC)
    assert [b["trade_date"] for b in bars] == [date(2026, 11, 4), THU]
    wed = bars[0]
    assert (wed["open"], wed["high"], wed["low"], wed["close"], wed["volume"], wed["open_interest"]) == (None, None, None, None, None, 16282)
    assert bars[1]["close"] == bar("GOLD", DEC, THU)["close"] and isinstance(bars[1]["volume"], int)
    assert dropped == {"no_date": 1, "other_contract": 1, "no_values": 1, "not_a_row": 1}
    # negative control: without an expiry_date field a row is not judged to be another contract's
    nofield = {k: v for k, v in bar("GOLD", FEB, THU).items() if k != "expiry_date"}
    assert len(mcx_daily.parse_rows([nofield], DEC)[0]) == 1
    assert (mcx_daily.num("1,39,341.5"), mcx_daily.num(True), mcx_daily.num(float("nan")), mcx_daily.num("x")) == (139341.5, None, None, None)


# ── design point 1: gold_curve is never written ──────────────────────────────────────────────────────────────────

def test_the_job_never_touches_gold_curve(masters):
    def snapshot():
        return db.query_df(masters, "SELECT * FROM gold_curve ORDER BY trade_date, exchange, symbol, expiry, source")

    before, contracts_before = snapshot(), mcx_close.contracts_for(masters, THU)
    curve_before = reads.curve(masters, exchange="MCX", day=THU)["rows"]
    res = _run(masters, FakeBreeze())
    assert res["inserted"] > 0 and len(_rows(masters)) > 0                     # control: the job did store rows …
    pd.testing.assert_frame_equal(snapshot(), before)                          # … none of them in gold_curve
    assert mcx_close.contracts_for(masters, THU) == contracts_before and reads.curve(masters, exchange="MCX", day=THU)["rows"] == curve_before
    assert "gold_mcx_daily" in schema.GOLD_TABLES and schema.FRESHNESS_COLUMN["gold_mcx_daily"] == "trade_date"


# ── the read ─────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(store):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    gold_api.configure(get_store=lambda: store, submit=lambda kind, fn: {"result": fn(lambda a, b: None)},
                       http=FakeHttp(default=FakeResponse(404, "")))
    app = FastAPI()
    app.include_router(gold_api.router)
    catalog_seed.seed(store)
    return TestClient(app)


def test_the_read_serves_the_rows_with_iso_dates_and_utc_offsets(client, masters):
    _run(masters, FakeBreeze())
    r = client.get("/db/gold/mcx/daily", params={"family": "GOLD", "expiry": "2026-12-04", "from": "2026-11-02", "to": "2026-11-05"})
    assert r.status_code == 200
    body = r.json()
    assert [x["trade_date"] for x in body["rows"]] == ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"] and body["count"] == 4
    last = body["rows"][-1]
    assert (last["family"], last["expiry"], last["open_interest"], last["unit"], last["source"], last["quality"]) == (
        "GOLD", "2026-12-04", 10005, "INR/10g", "breeze_daily", "broker")
    assert last["release_at"] == last["first_seen_at"] == "2026-11-06T04:05:00+00:00"           # never a naive datetime
    assert body["source"] == "breeze_daily" and body["from"] == "2026-11-02" and body["to"] == "2026-11-05"
    # negative controls: the family / expiry filters hold, and bad input is a 422
    other = client.get("/db/gold/mcx/daily", params={"family": "GOLDM", "from": "2026-11-02"}).json()["rows"]
    assert other and {x["family"] for x in other} == {"GOLDM"}
    allm = client.get("/db/gold/mcx/daily", params={"from": "2026-11-05", "to": "2026-11-05"}).json()["rows"]
    assert {(x["family"], x["expiry"]) for x in allm} == {("GOLD", "2026-12-04"), ("GOLD", "2027-02-05"), ("GOLDM", "2026-11-05"),
                                                          ("GOLDM", "2026-12-04")}
    assert client.get("/db/gold/mcx/daily", params={"family": "SILVER"}).status_code == 422
    assert client.get("/db/gold/mcx/daily", params={"from": "05-11-2026x"}).status_code == 422
