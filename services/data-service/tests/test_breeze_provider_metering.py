"""The live-quote provider's Breeze calls must be metered — and a refusal must not be amplified.

F9-03: `providers/icici_breeze_provider.py` held three unmetered `self._breeze.*` calls on the busiest Breeze
path in the stack — the live-quote method that `main.py`'s NIFTY and watchlist pollers drive every 15 s, whose
own comment prices it at ~1,580 calls a day (32 % of the daily quota). The shared ledger, the budget panel and
the 100/min · 5,000/day guard could not see a single one, so `/api/positions/breeze-budget` reported thousands
of calls remaining while that volume drained the real quota. On a trading day the first symptom would have been
the option chain and margin failing mid-session with the panel still showing plenty left.

Metering it introduced a second trap worth pinning: the ledger's `BudgetExceeded` is a `RuntimeError`, and
these methods retried on `RuntimeError` — so a refusal would have become three attempts with exponential
backoff, each asking the ledger again. A refusal is a decision, not a transient fault.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DS = Path(__file__).resolve().parents[1]
REPO = DS.parents[1]
for p in (str(REPO), str(DS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared.breeze_budget import BudgetExceeded              # noqa: E402
import providers.icici_breeze_provider as prov               # noqa: E402


def _provider(sdk: object) -> object:
    p = prov.ICICIBreezeProvider.__new__(prov.ICICIBreezeProvider)
    p._breeze = sdk
    p._require_connection = lambda: None
    p._resolve_isec_code = lambda t: "INFY"
    return p


def test_every_sdk_call_in_the_provider_is_inside_a_ledger_guard() -> None:
    """The source-level check, so a new call site cannot quietly skip the guard."""
    src = Path(prov.__file__).read_text(encoding="utf-8")
    assert src.count("ledger().guard(") == 3, "a Breeze call site was added or lost its guard"
    for method in ("get_quotes", "get_historical_data_v2"):
        assert f'self._breeze.{method}(' in src
    # the guard must come BEFORE the call, not after it
    for marker in ('with ledger().guard("data-service.live_quote", "get_quotes"):',
                   'with ledger().guard("data-service.intraday", "get_historical_data_v2"):',
                   'with ledger().guard("data-service.history", "get_historical_data_v2"):'):
        assert marker in src, marker


def test_the_retry_predicate_retries_faults_but_never_a_refusal() -> None:
    refusal = BudgetExceeded(SimpleNamespace(reason="per-day cap reached", allowed=False))
    assert prov._retry_real_errors(RuntimeError("transient")) is True
    assert prov._retry_real_errors(refusal) is False, "a budget refusal must not be retried"
    assert prov._retry_real_errors(ValueError("x")) is False


def test_a_transient_fault_still_retries_three_times() -> None:
    """The control: the fix must not have disabled the retry it narrowed."""
    seen = {"n": 0}

    class Flaky:
        def get_quotes(self, **kw):
            seen["n"] += 1
            raise RuntimeError("transient")

    with pytest.raises(RuntimeError):
        _provider(Flaky()).get_live_quote("INFY")
    assert seen["n"] == 3, f"the retry stopped working: {seen['n']} attempts"


def test_a_refusal_asks_the_ledger_once_and_never_reaches_the_sdk(monkeypatch) -> None:
    asked, called = {"n": 0}, {"n": 0}

    class Refusing:
        def guard(self, caller: str, method: str = ""):
            asked["n"] += 1
            raise BudgetExceeded(SimpleNamespace(reason="cap", allowed=False))

    class Sdk:
        def get_quotes(self, **kw):
            called["n"] += 1
            return {}

    monkeypatch.setattr(prov, "ledger", lambda: Refusing())
    with pytest.raises(BudgetExceeded):
        _provider(Sdk()).get_live_quote("INFY")
    assert asked["n"] == 1, f"the refusal was retried {asked['n']}x — exactly what the predicate must prevent"
    assert called["n"] == 0, "the SDK was called despite the refusal"
