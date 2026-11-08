"""The mid-session ICICI login guard: it must re-login when a session dies in market hours, and stay silent otherwise.

Source-level checks (the controller module pulls in the whole stack, so these assert the contract that matters and each
has a negative control). The security rule is the sharpest one: the connection-status payload embeds the API key in
`login_url`, so the guard may read only the booleans and the short error_kind — never log or alert the payload.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "master_controller.py").read_text()
BODY = SRC[SRC.index("async def icici_session_guard"):SRC.index("async def india_imports_watch")]


def test_it_is_scheduled_through_market_hours_but_clear_of_the_freeze_window():
    i = SRC.index('id="icici_session_guard"')
    first = SRC[max(0, i - 300):i]
    assert 'minute="30,45"' in first and "hour=9" in first, "the 9 o'clock hour must start at 09:30"
    j = SRC.index('id="icici_session_guard_day"')
    rest = SRC[max(0, j - 300):j]
    assert 'minute="*/15"' in rest and 'hour="10-15"' in rest
    # negative control: NEITHER of the guard's own triggers spans the 9 o'clock hour wholesale, which would fire at
    # 09:00 and 09:15 inside 07:45-09:20. (Another job may legitimately use that range; this is about this guard.)
    assert 'hour="9-15"' not in first and 'hour="9-15"' not in rest


def test_it_never_touches_the_fields_that_carry_the_api_key():
    # the rule is "never READ it" — the guard's own comment naming the field is the documentation of that rule,
    # so assert on access syntax, not on the word appearing anywhere in the function.
    for field in ("login_url", "token_hint", "customer_id"):
        for access in (f'get("{field}")', f'["{field}"]', f"get('{field}')", f"['{field}']"):
            assert access not in BODY, f"the guard must not read {field}"
    # it reads only the two booleans and the short kind
    assert '"connected"' in BODY and '"needs_session_refresh"' in BODY and '"error_kind"' in BODY
    # and never logs a whole body
    assert not re.search(r"(_log|_alerts)\.[a-z]+\([^)]*\bbody\b", BODY), "must not log the payload"
    assert not re.search(r"json\.dumps\(\s*body", BODY)


def test_it_refuses_to_act_in_the_cases_that_would_do_harm():
    assert "if not ICICI_AUTO_LOGIN" in BODY                 # opt-out honoured
    assert "_login_running()" in BODY                        # never interrupts a running login
    assert "SESSION_GUARD_MAX_PER_DAY" in BODY               # a broker refusal cannot loop all day
    assert "weekday() >= 5" in BODY and "special_session_on" in BODY   # not on a non-trading day, but Muhurat counts


def test_it_is_quiet_when_the_session_is_healthy():
    # the healthy path returns before any alert
    pre = BODY[:BODY.index("_SESSION_GUARD_TRIES[day] =")]
    assert "if alive:" in pre and "return" in pre
    assert "_alerts" not in pre, "a healthy session must produce no Telegram line"


def test_it_reports_both_outcomes_after_trying():
    post = BODY[BODY.index("_SESSION_GUARD_TRIES[day] ="):]
    assert "_alerts.info" in post and "ICICI session recovered" in post
    assert "_alerts.error" in post and "still down" in post
    assert "await icici_session_refresh()" in post           # it uses the one login path, not its own
