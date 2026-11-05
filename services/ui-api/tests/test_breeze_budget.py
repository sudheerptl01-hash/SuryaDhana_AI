"""shared/breeze_budget.py — the Breeze budget ledger (Terminal v2 PLAN §0.11; G6 "budget ledger refuses past the cap").

Every rule has a negative control: under the cap the call is allowed and counted; at the cap it is refused BEFORE the
SDK runs (the guard raises, the body never executes); the minute window slides; the day resets at IST midnight; a
caller's quota binds only that caller; the caps clamp to ICICI's documented ceiling; counters persist across instances
on the same file; the status report carries no secret-looking keys; positions._breeze_call goes through the ledger.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import breeze_budget as bb  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


class Clock:
    def __init__(self, start: datetime) -> None:
        self.t = start.timestamp()

    def __call__(self) -> float:
        return self.t

    def tick(self, s: float) -> None:
        self.t += s


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 11, 5, 10, 0, tzinfo=IST))


@pytest.fixture
def ledger(tmp_path: Path, clock: Clock) -> bb.BreezeBudget:
    return bb.BreezeBudget(tmp_path / "budget.sqlite", cap_minute=5, cap_day=12, quotas={"chain_poller": 3}, clock=clock)


def test_under_the_cap_is_allowed_and_counted(ledger: bb.BreezeBudget) -> None:
    d = ledger.acquire("ui-api.positions", "get_funds")
    assert d.allowed and d.used_day == 1 and d.used_minute == 1 and d.caller_used_day == 1 and d.call_id
    st = ledger.status()
    assert st["used_day"] == 1 and st["by_caller"] == {"ui-api.positions": 1} and st["by_method"] == {"get_funds": 1}
    assert st["remaining_day"] == 11 and st["refused_today"] == 0


def test_hard_stop_at_the_day_cap_refuses_before_the_body_runs(ledger: bb.BreezeBudget, clock: Clock) -> None:
    for _ in range(12):
        ledger.acquire("a", "m")
        clock.tick(13)                       # stay under the minute cap
    ran = []
    with pytest.raises(bb.BudgetExceeded) as exc, ledger.guard("a", "m"):
        ran.append(1)                        # never reached
    assert not ran
    assert "day cap" in str(exc.value) and exc.value.retry_after_s is not None and exc.value.retry_after_s > 0
    assert ledger.status()["refused_today"] == 1 and ledger.status()["used_day"] == 12


def test_minute_cap_slides(ledger: bb.BreezeBudget, clock: Clock) -> None:
    for _ in range(5):
        ledger.acquire("a", "m")
    with pytest.raises(bb.BudgetExceeded) as exc:
        ledger.acquire("a", "m")
    assert "minute cap" in str(exc.value) and 0 < exc.value.retry_after_s <= 60
    clock.tick(61)                           # the window slid: allowed again (negative control of the refusal)
    assert ledger.acquire("a", "m").allowed


def test_caller_quota_binds_only_that_caller(ledger: bb.BreezeBudget, clock: Clock) -> None:
    for _ in range(3):
        ledger.acquire("chain_poller", "get_option_chain_quotes")
        clock.tick(13)
    with pytest.raises(bb.BudgetExceeded) as exc:
        ledger.acquire("chain_poller", "get_option_chain_quotes")
    assert "caller quota" in str(exc.value)
    assert ledger.acquire("ui-api.margin", "margin_calculator").allowed      # another caller still has budget
    assert ledger.decide("chain_poller").allowed is False and ledger.status()["refused_today"] == 1


def test_day_resets_at_ist_midnight(tmp_path: Path) -> None:
    clk = Clock(datetime(2026, 11, 5, 23, 59, 30, tzinfo=IST))
    led = bb.BreezeBudget(tmp_path / "b.sqlite", cap_minute=100, cap_day=2, clock=clk)
    led.acquire("a", "m")
    led.acquire("a", "m")
    with pytest.raises(bb.BudgetExceeded):
        led.acquire("a", "m")
    clk.tick(60)                             # 00:00:30 IST next day
    d = led.acquire("a", "m")
    assert d.allowed and d.used_day == 1 and bb.ist_day(clk()) == "2026-11-06"


def test_caps_clamp_to_the_documented_ceiling(tmp_path: Path) -> None:
    led = bb.BreezeBudget(tmp_path / "c.sqlite", cap_minute=10_000, cap_day=99_999)
    assert led.cap_minute == bb.DOC_LIMIT_PER_MINUTE == 100 and led.cap_day == bb.DOC_LIMIT_PER_DAY == 5000
    led2 = bb.BreezeBudget(tmp_path / "d.sqlite", cap_minute=0, cap_day=-1)       # nonsense → defaults
    assert led2.cap_minute == bb.DEFAULT_CAP_PER_MINUTE and led2.cap_day == bb.DEFAULT_CAP_PER_DAY
    assert bb.DEFAULT_CALLER_QUOTAS == {"chain_poller": 700}                      # O-T6 pilot default


def test_counters_persist_across_instances_on_one_file(tmp_path: Path, clock: Clock) -> None:
    path = tmp_path / "shared.sqlite"
    a = bb.BreezeBudget(path, cap_day=3, clock=clock)
    a.acquire("x", "m")
    a.acquire("x", "m")
    b = bb.BreezeBudget(path, cap_day=3, clock=clock)                              # another process
    assert b.acquire("x", "m").used_day == 3
    with pytest.raises(bb.BudgetExceeded):
        b.acquire("x", "m")


def test_guard_records_the_outcome_and_errors_still_count(ledger: bb.BreezeBudget) -> None:
    with pytest.raises(RuntimeError), ledger.guard("a", "m"):
        raise RuntimeError("sdk error")
    with ledger.guard("a", "m"):
        pass
    st = ledger.status()
    assert st["used_day"] == 2 and st["errors_today"] == 1 and st["last_call"]["ok"] == 1


def test_parse_quotas_and_status_carry_no_secrets(ledger: bb.BreezeBudget) -> None:
    assert bb.parse_quotas("chain_poller=900, tick_engine=1200, bad, x=-1") == {"chain_poller": 900, "tick_engine": 1200}
    assert bb.parse_quotas(None) == bb.DEFAULT_CALLER_QUOTAS
    st = ledger.status()
    assert not {k for k in st if "token" in k or "secret" in k or "key" in k}
    assert st["ceiling_day"] == 5000 and st["ceiling_minute"] == 100


def test_process_ledger_uses_a_temp_file_under_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(bb.ENV_DB, raising=False)
    bb.reset_ledger()
    led = bb.ledger()
    assert "suryadhana-tests" in str(led.path) and "data" not in led.path.parts[-3:]
    bb.reset_ledger()


def test_positions_breeze_call_goes_through_the_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(bb.ENV_DB, str(tmp_path / "pos.sqlite"))
    monkeypatch.setenv(bb.ENV_CAP_DAY, "1")
    bb.reset_ledger()
    import routers.positions as pos

    def get_funds() -> dict:
        return {"Success": {}}

    assert pos._breeze_call(get_funds) == {"Success": {}}
    with pytest.raises(bb.BudgetExceeded):
        pos._breeze_call(get_funds)
    st = pos.breeze_budget_status()
    assert st["by_caller"] == {pos.BREEZE_BUDGET_CALLER: 1} and st["by_method"] == {"get_funds": 1} and st["refused_today"] == 1
    bb.reset_ledger()
