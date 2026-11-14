"""shared/breeze_budget.py — the Breeze budget ledger (Terminal v2 PLAN §0.11; G6 "budget ledger refuses past the cap").

Every rule has a negative control: under the cap the call is allowed and counted; at the cap it is refused BEFORE the
SDK runs (the guard raises, the body never executes); the minute window slides; the day resets at IST midnight; a
caller's quota binds only that caller; the caps clamp to ICICI's documented ceiling; counters persist across instances
on the same file; the status report carries no secret-looking keys; positions._breeze_call goes through the ledger, and so
do the trades route's get_order_list and the client's generate_session (a day cap of 0 refuses both before the SDK runs).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import ClassVar
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
    # The O-T6 pilot value that still has a caller must not drift.  was removed in F15: no code
    # ever declared it, so its 700/day reserved a share of the cap for a caller that does not exist.
    assert "chain_poller" not in bb.DEFAULT_CALLER_QUOTAS
    assert bb.DEFAULT_CALLER_QUOTAS["iv_intraday"] == 800          # the fo_iv pilot's caller, PLAN 1.1
    # …and F10-02: every caller that spends quota must HAVE a quota. The live-quote poller went unmetered and
    # therefore unbounded until 14 Nov, and it is the biggest spender in the stack (~1,580/day for the NIFTY
    # poller alone, plus one call per starred symbol every 15 s with no websocket shortcut). An unbounded
    # fallback can empty a 4,000/day cap before lunch and the first symptom is the chain failing mid-session.
    for caller in ("data-service.live_quote", "data-service.intraday", "data-service.history",
                   "execution.ltp", "execution.order_status", "execution.portfolio", "live_execution.ltp"):
        assert bb.DEFAULT_CALLER_QUOTAS.get(caller, 0) > 0, f"{caller} spends quota with no quota of its own"
    # They deliberately SUM ABOVE cap_day: a quota caps one caller's share so no single path can empty the day,
    # while cap_day stays the real ceiling. Scaling them to sum to the cap would reserve quota for callers that
    # are idle most days (the execution ones are dormant) and starve the live ones.
    assert sum(bb.DEFAULT_CALLER_QUOTAS.values()) > bb.DEFAULT_CAP_PER_DAY
    assert max(bb.DEFAULT_CALLER_QUOTAS.values()) < bb.DEFAULT_CAP_PER_DAY, "no single caller may own the day"
    assert bb.DEFAULT_CALLER_QUOTAS.get("iv_intraday", 800) == 800


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
    assert bb.parse_quotas("chain_poller=900, tick_engine=1200, bad, x=-1") == {**bb.DEFAULT_CALLER_QUOTAS, "chain_poller": 900, "tick_engine": 1200}
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
    st = pos.budget_counters()
    assert st["by_caller"] == {pos.BREEZE_BUDGET_CALLER: 1} and st["by_method"] == {"get_funds": 1} and st["refused_today"] == 1
    bb.reset_ledger()


# ── every Breeze call in routers/positions.py goes through the ledger (check:B3-API majors) ─────────────────────
class _OrderBreeze:
    """A fake BreezeConnect: records every SDK call; never opens a socket."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_order_list(self, **kw: object) -> dict:
        self.calls.append(dict(kw))
        return {"Status": 200, "Success": [{"order_id": "X1", "stock_code": "INFY", "action": "buy", "quantity": "2",
                                            "average_price": "1500.5", "status": "Executed", "order_type": "limit",
                                            "order_datetime": "04-Nov-2026 10:01:02"}]}


@pytest.fixture
def pos_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(bb.ENV_DB, str(tmp_path / "pos_routes.sqlite"))
    monkeypatch.delenv(bb.ENV_CAP_DAY, raising=False)
    bb.reset_ledger()
    import routers.positions as pos
    yield pos
    bb.reset_ledger()


def test_trade_history_route_records_one_get_order_list_ledger_entry(pos_ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    pos = pos_ledger
    fake = _OrderBreeze()
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (fake, None))
    body = pos.get_trade_history(limit=10)
    assert body["connected"] is True and body["total_trades"] == 1 and body["trades"][0]["symbol"] == "INFY"
    assert len(fake.calls) == 1 and fake.calls[0]["exchange_code"] == "NSE"
    st = pos.budget_counters()
    assert st["by_method"] == {"get_order_list": 1} and st["by_caller"] == {pos.BREEZE_BUDGET_CALLER: 1}
    assert st["used_day"] == 1 and st["refused_today"] == 0


def test_trade_history_day_cap_zero_refuses_before_the_sdk_runs(pos_ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control: a day cap of 0 — the route answers 'budget' and the SDK method is never called."""
    pos = pos_ledger
    fake = _OrderBreeze()
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (fake, None))
    led = bb.ledger()
    led.cap_day = 0                                    # the env clamp turns 0 into the default; the attribute is the cap
    body = pos.get_trade_history(limit=10)
    assert fake.calls == [], "the SDK ran past the cap"
    assert body["ok"] is False and body["error_kind"] == "budget" and body["trades"] == [] and "budget" in body["error"]
    st = led.status()
    assert st["used_day"] == 0 and st["refused_today"] == 1


class _FakeBreezeConnect:
    sessions: ClassVar[list[str]] = []

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def generate_session(self, api_secret: str, session_token: str) -> None:
        _FakeBreezeConnect.sessions.append(session_token[:2])


def _fake_breeze_module(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    import shared.breeze_cache as cache_mod
    monkeypatch.setattr(cache_mod, "install", lambda: None)                 # never the security-master download
    mod = types.ModuleType("breeze_connect")
    mod.BreezeConnect = _FakeBreezeConnect  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "breeze_connect", mod)
    _FakeBreezeConnect.sessions = []


def test_generate_session_goes_through_the_ledger(pos_ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    pos = pos_ledger
    _fake_breeze_module(monkeypatch)
    client, err, kind = pos._build_breeze_client("k", "s", "tok")
    assert err is None and kind is None and isinstance(client, _FakeBreezeConnect) and _FakeBreezeConnect.sessions == ["to"]
    st = pos.budget_counters()
    # F12: the login has its own caller label now, so a holdings runaway cannot exhaust the share the one
    # call the terminal cannot do without depends on.
    assert st["by_method"] == {"generate_session": 1} and st["by_caller"] == {pos.BREEZE_LOGIN_CALLER: 1}


def test_generate_session_refused_at_the_cap_before_the_sdk_runs(pos_ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control: past the cap the login is not attempted and the client reports the budget, not a login error."""
    pos = pos_ledger
    _fake_breeze_module(monkeypatch)
    bb.ledger().cap_day = 0
    client, err, kind = pos._build_breeze_client("k", "s", "tok")
    assert client is None and kind == "budget" and "budget" in (err or "").lower()
    assert _FakeBreezeConnect.sessions == [] and bb.ledger().status()["refused_today"] == 1


def test_every_caller_name_in_the_code_has_a_quota() -> None:
    """A caller that can spend quota must have a quota — enforced from the SOURCE, not from the live ledger.

    F11-01: the first quota pass covered the callers that had just been named in that same commit and left the
    stack's actual spenders unbounded. Measured against data/breeze_budget.sqlite at the time: 7 of the 9
    entries belonged to callers that had never made a single call, while `ui-api.positions` (1,039 calls
    all-time, including the 14 Nov login runaway) had none at all. That is the same scope-not-logic mistake the
    ledger gate made with its roots, one commit later.

    Reading the ledger would only ever catch a caller AFTER it had spent; reading the code catches it before it
    ever runs, which is the point of a quota.
    """
    from shared.breeze_budget import DEFAULT_CALLER_QUOTAS

    # R18-C: ONE scan, shared with the two sibling gates. This test carried its own copy of the patterns and
    # the root walk — three scans of the same tree, which is how they drifted: the sibling learned the
    # *_CALLER constant pattern while this one had already had it, and nothing kept them in step. Whatever
    # `_declared_callers()` can see is what every quota gate sees.
    found = _declared_callers()

    missing = {c: where for c, where in found.items()
               if c not in DEFAULT_CALLER_QUOTAS and not c.isupper()}      # CALLER constants resolve at runtime
    assert not missing, (
        "these callers can spend Breeze quota with no quota of their own — one unbounded path can empty the "
        f"day and the chain fails mid-session: {missing}")


def _constant_values() -> dict[str, str]:
    """`{CONSTANT_NAME: "its string value"}` for every `*_CALLER*` constant in the scanned roots."""
    import re as _re

    from test_breeze_ledger_coverage import SCANNED_ROOTS

    out: dict[str, str] = {}
    pat = _re.compile(r'^([A-Z_]*CALLER[A-Z_]*)\s*=\s*["\']([\w.\-]+)["\']', _re.M)
    for root in SCANNED_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if "/tests/" in str(path):
                continue
            code = "\n".join(ln.split("#", 1)[0] for ln in path.read_text(encoding="utf-8").split("\n"))
            for m in pat.finditer(code):
                out.setdefault(m.group(1), m.group(2))
    return out


def _declared_callers() -> dict[str, str]:
    """Every Breeze caller label the CODE declares, as {label: file}.

    Shared by both quota gates: one asserts every declared caller has a quota, the other that every quota
    belongs to a declared caller. They were two copies of this scan, and the second copy referenced the
    first's locals — so it raised NameError instead of checking anything.
    """
    import ast
    import re as _re

    from test_breeze_ledger_coverage import SCANNED_ROOTS

    pats = (_re.compile(r'\.guard\(\s*["\']([\w.\-]+)["\']'),
            _re.compile(r'caller\s*=\s*["\']([\w.\-]+)["\']'),
            _re.compile(r'^[A-Z_]*CALLER[A-Z_]*\s*=\s*["\']([\w.\-]+)["\']', _re.M))
    found: dict[str, str] = {}
    scanned = 0
    for root in SCANNED_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if "/tests/" in str(path):
                continue
            scanned += 1
            src = path.read_text(encoding="utf-8")
            try:
                ast.parse(src)
            except SyntaxError:                                # pragma: no cover
                continue
            code_only = "\n".join(ln.split("#", 1)[0] for ln in src.split("\n"))
            for pat in pats:
                for m in pat.finditer(code_only):
                    found.setdefault(m.group(1), str(path))
    assert scanned > 100, f"only {scanned} modules scanned — are the roots right?"
    assert len(found) >= 8, f"only {len(found)} caller labels found — the patterns stopped matching: {found}"
    return found


def test_no_quota_belongs_to_a_caller_the_code_never_declares() -> None:
    """A quota for a caller nothing declares is dead weight that READS as coverage.

    R16: this assertion used to sit inside the peak test, AFTER a `pytest.skip("no live ledger")` on
    data/breeze_budget.sqlite — which is gitignored. So the one check that caught `chain_poller` (700/day
    reserved for a caller that never existed) was dead in CI and on every fresh checkout, and would have
    stayed dead silently. It is pure source analysis and needs no ledger, so it runs on its own.
    """
    from shared.breeze_budget import DEFAULT_CALLER_QUOTAS

    orphans = sorted(c for c in DEFAULT_CALLER_QUOTAS if c not in _declared_callers())
    assert not orphans, (
        f"quota(s) for callers no code declares — either the caller was renamed and its quota left behind, "
        f"or the quota is aspirational: {orphans}")


def test_every_generate_session_site_shares_one_caller_label() -> None:
    """The login's bound is a CALLER quota, so two labels on the same call means two bounds and neither one
    governs it — which is what `ui-api.probe` vs `ui-api.login` was. The comment next to the fix says "a bound
    you can dodge by relabelling is not a bound"; nothing asserted it (R16). The ledger has no method
    dimension, so this is the only place that can."""
    import re

    from test_breeze_ledger_coverage import SCANNED_ROOTS

    labels: dict[str, str] = {}
    for root in SCANNED_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if "/tests/" in str(path):
                continue
            code = "\n".join(ln.split("#", 1)[0] for ln in path.read_text(encoding="utf-8").split("\n"))
            for m in re.finditer(r'\.guard\(\s*([^,]+),\s*["\']generate_session["\']', code):
                labels[m.group(1).strip()] = str(path)

    assert labels, "no generate_session guard site found — the patterns stopped matching"

    # Resolve each label to its VALUE. The first version guessed from the constant's NAME ("LOGIN" in it),
    # which would have called any future `BREEZE_LOGIN_PROBE_CALLER = "ui-api.probe"` a login — a gate that
    # infers from a name cannot see a name that lies. _declared_callers() already maps every constant to the
    # string it holds, so the value is available and nothing has to be guessed.
    declared = _declared_callers()
    resolved: set[str] = set()
    for lbl in labels:
        lit = lbl.strip().strip('"\'')
        if lit in declared:                            # already a literal caller label
            resolved.add(lit)
            continue
        const = lit.rsplit(".", 1)[-1]                 # e.g. pos.BREEZE_LOGIN_CALLER -> BREEZE_LOGIN_CALLER
        value = _constant_values().get(const)
        assert value, f"could not resolve the caller constant {lbl} to a value — {labels}"
        resolved.add(value)

    assert len(resolved) == 1, (
        f"generate_session is guarded under more than one caller label, so no single quota governs the login: "
        f"{labels} -> {resolved}")
    assert resolved == {"ui-api.login"}, (
        f"the login is metered under {resolved}, not ui-api.login — its quota governs nothing")


def test_no_quota_sits_at_its_observed_peak() -> None:
    """A quota must have real headroom over what that caller has actually spent in a day.

    F13-07: `ui-api.login` was first set to 120 against the 115 login attempts made that very day — 96% of its
    own bound, and the identical arithmetic the same commit had just fixed for `ui-api.positions` (600 against
    a 578 peak). The day attempts pile up is a failing-TOTP day, and a refused `generate_session` means no
    broker session for the REST OF THE DAY even if the owner answers the OTP. The one call the terminal cannot
    do without must get the most headroom, not the least.

    Measured from the live ledger when it exists, so the bound is checked against reality rather than against
    the number someone assumed. Quotas are per DAY, so the comparison is a per-day peak, never an all-time sum
    (F13-08: an earlier commit message quoted 1,038 all-time where the peak that matters was 578).
    """
    import sqlite3

    from shared.breeze_budget import DEFAULT_CALLER_QUOTAS

    ledger_db = Path(__file__).resolve().parents[3] / "data" / "breeze_budget.sqlite"
    if not ledger_db.exists():                                  # pragma: no cover — a fresh machine
        pytest.skip("no live ledger to measure against")
    con = sqlite3.connect(f"file:{ledger_db}?mode=ro", uri=True, timeout=5.0)
    try:
        peaks: dict[str, int] = {}
        for caller, _day, n in con.execute("SELECT caller, day, COUNT(*) FROM calls GROUP BY caller, day"):
            peaks[str(caller)] = max(peaks.get(str(caller), 0), int(n))
    finally:
        con.close()

    tight = {c: (n, DEFAULT_CALLER_QUOTAS[c]) for c, n in peaks.items()
             if c in DEFAULT_CALLER_QUOTAS and n > DEFAULT_CALLER_QUOTAS[c] * 0.8}
    assert not tight, (
        "quota(s) within 20% of a peak this caller has already reached — the day it is exceeded is the day "
        f"the terminal needs the call most: {tight}")

    # The login specifically, because its refusal is the one that cannot be worked around. Sized off the
    # METHOD rather than any caller label: generate_session is the same ICICI call whoever makes it, and the
    # first version read `peaks["ui-api.login"] or peaks["ui-api.positions"]`, an `or` chain that silently
    # measured nothing once the calls moved to a third label. A method-level peak cannot be relabelled away.
    con = sqlite3.connect(f"file:{ledger_db}?mode=ro", uri=True, timeout=5.0)
    try:
        login_peak = max((int(n) for _d, n in con.execute(
            "SELECT day, COUNT(*) FROM calls WHERE method = 'generate_session' GROUP BY day")), default=0)
    finally:
        con.close()
    assert login_peak > 0, "no generate_session rows — this assertion would pass vacuously"
    # R16: this is a REPORT, not a tripwire. Asserting `quota >= peak * 1.5` against a ledger that grows every
    # day means a busy login day turns the suite red with no code change, and a test that fails for reasons
    # outside the diff is one people learn to re-run rather than read. The hard requirement is only that the
    # quota is not already exceeded; the headroom advisory is printed so a human decides.
    assert DEFAULT_CALLER_QUOTAS["ui-api.login"] > login_peak, (
        f"the login quota ({DEFAULT_CALLER_QUOTAS['ui-api.login']}) is at or below its worst observed day "
        f"({login_peak} generate_session calls) — the day it is exceeded is the day the terminal needs the "
        f"call most, and no retry can work around a refused login")
    if DEFAULT_CALLER_QUOTAS["ui-api.login"] < login_peak * 1.5:
        print(f"\nNOTE: login quota {DEFAULT_CALLER_QUOTAS['ui-api.login']} is under 1.5x the observed peak "
              f"({login_peak}); consider raising it before it bites.")




def test_the_mcx_window_is_not_served_for_years_the_calendar_cannot_speak_for() -> None:
    """R15-B: `mcx_specs.CALENDAR_YEARS` is (2026,), and outside those years `trading_window` answers on the
    WEEKEND RULE ALONE — it would report a normal 09:00–23:55 window on a 2027 MCX holiday.

    Serving that as fact would make the BRKR chip paint red DOWN all evening over a shut exchange, every
    holiday of 2027, with nothing in the code saying when it started lying. "We do not know" is a different
    answer from "it is open", and the UI already has a branch for it: the field is omitted and the chip falls
    back to its weekday heuristic.
    """
    from datetime import date

    from shared import mcx_specs

    # the premise: outside CALENDAR_YEARS the calendar is weekend-only, so a holiday looks like a normal day
    assert 2027 not in mcx_specs.CALENDAR_YEARS
    assert mcx_specs.trading_window(date(2027, 1, 4)) is not None, (
        "the premise changed — trading_window now refuses unknown years itself, so the guard below can go")

    # and the endpoint must gate on it, in the same expression that reads the window
    src = (Path(__file__).resolve().parents[1] / "routers" / "positions.py").read_text(encoding="utf-8")
    code = "\n".join(ln.split("#", 1)[0] for ln in src.split("\n"))
    assert ("CALENDAR_YEARS" in code or "calendar_covers" in code), (
        "the budget endpoint serves mcx_window without checking the calendar covers that year — from "
        "1 Jan 2027 the chip would call every MCX holiday a trading evening")
    guard = [ln for ln in code.split("\n") if "CALENDAR_YEARS" in ln or "calendar_covers" in ln]
    assert guard, "the year guard vanished"


def test_last_call_is_todays_last_call(tmp_path) -> None:
    """R15-D: `status()` scoped every counter to the IST day except `last_call`, which took the newest row
    ever. So a quiet morning rendered "0 calls today · last: 23:58 data-service.gold_vwap30" — two true facts
    arranged to look like one false one, on the panel the BRKR chip sends the owner to for a cause."""
    led = bb.BreezeBudget(tmp_path / "scoped.sqlite", cap_minute=60, cap_day=4000)
    with led.guard("yesterday.caller", "get_quotes"):
        pass
    # move the stored row into a previous day, leaving today empty
    led._conn.execute("UPDATE calls SET day = '2026-11-13'")
    led._conn.commit()

    st = led.status()
    assert st["used_day"] == 0, "the counters must already be day-scoped"
    assert st["last_call"] is None, (
        f"last_call leaked a previous day's row beside today's zero counters: {st['last_call']}")

    with led.guard("today.caller", "get_funds"):
        pass
    st2 = led.status()
    assert st2["last_call"] and st2["last_call"]["caller"] == "today.caller", st2["last_call"]
